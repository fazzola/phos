"""Behavior decisions that produce FaceState without drawing UI elements."""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import replace
from typing import Callable, Optional

from robot.ui.state import BlinkPhase, FaceExpression, FaceState

from .behaviors import Behavior
from .events import Event, EventBus
from .runtime import STATE_CHANGED
from .state import RobotState

VISION_EXPRESSION_STABLE = "vision.visual_expression_stable"
VISION_FACE_LOST = "vision.face_lost"
VISION_FACE_POSITION = "vision.face_position"


class BehaviorEngine(Behavior):
    """Translate Core/Vision events and idle timing into a current FaceState."""

    name = "behavior-engine"

    def __init__(
        self,
        events: EventBus,
        *,
        blink_interval: tuple[float, float] = (3.5, 6.5),
        gaze_interval: tuple[float, float] = (2.5, 5.5),
        face_gaze_smoothing: float = 0.35,
    ) -> None:
        if blink_interval[0] <= 0 or blink_interval[1] < blink_interval[0]:
            raise ValueError("Blink interval must contain positive ascending values.")
        if gaze_interval[0] <= 0 or gaze_interval[1] < gaze_interval[0]:
            raise ValueError("Gaze interval must contain positive ascending values.")
        if not 0.0 < face_gaze_smoothing <= 1.0:
            raise ValueError("face_gaze_smoothing must be between zero and one.")
        self._events = events
        self._blink_interval = blink_interval
        self._gaze_interval = gaze_interval
        self._face_gaze_smoothing = face_gaze_smoothing
        self._state = FaceState()
        self._robot_state = RobotState.IDLE
        self._blink_phase = BlinkPhase.OPEN
        self._blink_started_at = 0.0
        self._next_blink_at = 0.0
        self._next_gaze_at = 0.0
        self._face_is_tracked = False
        self._unsubscribers: list[Callable[[], None]] = []
        self._task: Optional[asyncio.Task[None]] = None

    @property
    def face_state(self) -> FaceState:
        return replace(
            self._state,
            blink_phase=self._blink_phase,
            blink_progress=self._blink_progress(time.monotonic()),
        ).normalized()

    async def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("Behavior engine is already running.")
        self._unsubscribers = [
            self._events.subscribe(STATE_CHANGED, self._on_robot_state),
            self._events.subscribe(VISION_EXPRESSION_STABLE, self._on_visual_expression),
            self._events.subscribe(VISION_FACE_POSITION, self._on_face_position),
            self._events.subscribe(VISION_FACE_LOST, self._on_face_lost),
        ]
        now = time.monotonic()
        self._next_blink_at = now + random.uniform(*self._blink_interval)
        self._next_gaze_at = now + random.uniform(*self._gaze_interval)
        self._task = asyncio.create_task(self._animation_loop(), name="behavior-engine")

    async def stop(self) -> None:
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers = []
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def wait(self) -> None:
        """Wait for the behavior task; used by the application supervisor."""
        if self._task is None:
            raise RuntimeError("Behavior engine is not running.")
        await asyncio.shield(self._task)

    async def _on_robot_state(self, event: Event) -> None:
        try:
            state = RobotState(event.data["current"])
        except (KeyError, ValueError) as error:
            raise ValueError("A core.state_changed event must contain a valid current state.") from error
        self._robot_state = state
        self._state = _face_state_for_robot_state(state)

    async def _on_visual_expression(self, event: Event) -> None:
        if self._robot_state is not RobotState.IDLE:
            return
        payload = event.data.get("visual_expression", {})
        expression = {
            "happy": FaceExpression.HAPPY,
            "surprised": FaceExpression.SURPRISED,
            "neutral": FaceExpression.NEUTRAL,
        }.get(payload.get("label"))
        if expression is not None:
            try:
                confidence = float(payload.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0
            self._state = replace(
                self._state,
                expression=expression,
                reaction_strength=max(0.0, min(confidence, 1.0)),
            )

    async def _on_face_lost(self, event: Event) -> None:
        self._face_is_tracked = False
        self._state = _face_state_for_robot_state(self._robot_state)

    async def _on_face_position(self, event: Event) -> None:
        payload = event.data.get("face_position", {})
        try:
            x = _clamp_unit(float(payload["x"]))
            y = _clamp_unit(float(payload["y"]))
        except (KeyError, TypeError, ValueError):
            return
        self._face_is_tracked = True
        if self._robot_state is not RobotState.IDLE:
            return
        target_x = x * 0.65
        target_y = y * 0.45
        self._state = replace(
            self._state,
            pupil_x=_smooth(self._state.pupil_x, target_x, self._face_gaze_smoothing),
            pupil_y=_smooth(self._state.pupil_y, target_y, self._face_gaze_smoothing),
        )

    async def _animation_loop(self) -> None:
        while True:
            now = time.monotonic()
            self._advance_blink(now)
            if self._robot_state is RobotState.IDLE and not self._face_is_tracked and now >= self._next_gaze_at:
                pupil_x, pupil_y = random.choice(_IDLE_GAZE_OFFSETS)
                self._state = replace(self._state, pupil_x=pupil_x, pupil_y=pupil_y)
                self._next_gaze_at = now + random.uniform(*self._gaze_interval)
            await asyncio.sleep(1.0 / 60.0)

    def _advance_blink(self, now: float) -> None:
        if self._blink_phase is BlinkPhase.OPEN and now >= self._next_blink_at:
            self._blink_phase = BlinkPhase.CLOSING
            self._blink_started_at = now
        elif self._blink_phase is BlinkPhase.CLOSING and now - self._blink_started_at >= 0.075:
            self._blink_phase = BlinkPhase.CLOSED
            self._blink_started_at = now
        elif self._blink_phase is BlinkPhase.CLOSED and now - self._blink_started_at >= 0.045:
            self._blink_phase = BlinkPhase.OPENING
            self._blink_started_at = now
        elif self._blink_phase is BlinkPhase.OPENING and now - self._blink_started_at >= 0.11:
            self._blink_phase = BlinkPhase.OPEN
            self._next_blink_at = now + random.uniform(*self._blink_interval)

    def _blink_progress(self, now: float) -> float:
        duration = {
            BlinkPhase.CLOSING: 0.075,
            BlinkPhase.CLOSED: 0.045,
            BlinkPhase.OPENING: 0.11,
        }.get(self._blink_phase)
        if duration is None:
            return 0.0
        return max(0.0, min((now - self._blink_started_at) / duration, 1.0))


def _face_state_for_robot_state(state: RobotState) -> FaceState:
    if state is RobotState.LISTENING:
        return FaceState(background="#075B66", expression=FaceExpression.CURIOUS, reaction_strength=0.70)
    if state is RobotState.THINKING:
        return FaceState(background="#35245E", expression=FaceExpression.CURIOUS, reaction_strength=0.55)
    if state is RobotState.SPEAKING:
        return FaceState(background="#164F3B", expression=FaceExpression.HAPPY, reaction_strength=0.55)
    if state is RobotState.SLEEPING:
        return FaceState(background="#08101E", expression=FaceExpression.SLEEPY, reaction_strength=1.0)
    if state is RobotState.ERROR:
        return FaceState(background="#6B1D2A", expression=FaceExpression.WORRIED, reaction_strength=0.80)
    return FaceState()


_IDLE_GAZE_OFFSETS = (
    (-0.35, 0.0),
    (0.35, 0.0),
    (0.0, -0.20),
    (0.0, 0.20),
    (-0.25, -0.15),
    (0.25, -0.15),
)


def _clamp_unit(value: float) -> float:
    return max(-1.0, min(value, 1.0))


def _smooth(current: float, target: float, amount: float) -> float:
    return current + (target - current) * amount
