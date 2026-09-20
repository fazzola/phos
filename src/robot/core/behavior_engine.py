"""Behavior decisions that produce FaceState without drawing UI elements."""

from __future__ import annotations

import asyncio
import math
import random
import time
from dataclasses import replace
from typing import Callable, Optional

from robot.ui.state import BlinkPhase, FaceExpression, FaceState, VisualAccent

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
        reaction_decay_per_second: float = 0.30,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if blink_interval[0] <= 0 or blink_interval[1] < blink_interval[0]:
            raise ValueError("Blink interval must contain positive ascending values.")
        if gaze_interval[0] <= 0 or gaze_interval[1] < gaze_interval[0]:
            raise ValueError("Gaze interval must contain positive ascending values.")
        if not 0.0 < face_gaze_smoothing <= 1.0:
            raise ValueError("face_gaze_smoothing must be between zero and one.")
        if reaction_decay_per_second <= 0.0:
            raise ValueError("reaction_decay_per_second must be positive.")
        self._events = events
        self._blink_interval = blink_interval
        self._gaze_interval = gaze_interval
        self._face_gaze_smoothing = face_gaze_smoothing
        self._reaction_decay_per_second = reaction_decay_per_second
        self._clock = clock
        self._state = FaceState()
        self._robot_state = RobotState.IDLE
        self._blink_phase = BlinkPhase.OPEN
        self._blink_started_at = 0.0
        self._next_blink_at = 0.0
        self._next_gaze_at = 0.0
        self._face_is_tracked = False
        self._last_reaction_update_at: Optional[float] = None
        self._surprise_armed = True
        self._surprise_last_at = float("-inf")
        self._unsubscribers: list[Callable[[], None]] = []
        self._task: Optional[asyncio.Task[None]] = None

    @property
    def face_state(self) -> FaceState:
        return replace(
            self._state,
            blink_phase=self._blink_phase,
            blink_progress=self._blink_progress(self._clock()),
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
        now = self._clock()
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
        try:
            confidence = float(payload.get("confidence", 0.0))
        except (TypeError, ValueError):
            return
        label = payload.get("label")
        reaction = _visual_reaction(label, confidence)
        if reaction is None:
            return
        now = self._clock()
        if label in {"happy", "happiness", "neutral"}:
            self._surprise_armed = True
        if label in {"surprise", "surprised"}:
            if not self._surprise_armed or now - self._surprise_last_at < 4.0:
                return
        if label in {"surprise", "surprised"}:
            self._surprise_armed = False
            self._surprise_last_at = now
        expression, accent, strength = reaction
        self._state = replace(self._state, expression=expression, accent=accent, reaction_strength=strength)
        self._last_reaction_update_at = self._clock()

    async def _on_face_lost(self, event: Event) -> None:
        self._face_is_tracked = False
        if self._robot_state is RobotState.IDLE:
            self._state = replace(self._state, pupil_x=0.0, pupil_y=0.0)

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
            now = self._clock()
            self._advance_blink(now)
            self._decay_visual_reaction(now)
            if self._robot_state is RobotState.IDLE and not self._face_is_tracked and now >= self._next_gaze_at:
                pupil_x, pupil_y = random.choice(_IDLE_GAZE_OFFSETS)
                self._state = replace(self._state, pupil_x=pupil_x, pupil_y=pupil_y)
                self._next_gaze_at = now + random.uniform(*self._gaze_interval)
            await asyncio.sleep(1.0 / 60.0)

    def _decay_visual_reaction(self, now: float) -> None:
        """Ease an idle Vision reaction back to PHOS's normal face."""
        if self._robot_state is not RobotState.IDLE or self._last_reaction_update_at is None:
            return
        elapsed = max(0.0, now - self._last_reaction_update_at)
        self._last_reaction_update_at = now
        strength = max(0.0, self._state.reaction_strength - elapsed * self._reaction_decay_per_second)
        expression = self._state.expression if strength > 0.0 else FaceExpression.NEUTRAL
        accent = self._state.accent if strength > 0.0 else VisualAccent.NEUTRAL
        self._state = replace(self._state, expression=expression, accent=accent, reaction_strength=strength)

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
        return FaceState(
            background="#075B66",
            expression=FaceExpression.CURIOUS,
            accent=VisualAccent.CURIOUS,
            reaction_strength=0.70,
        )
    if state is RobotState.THINKING:
        return FaceState(
            background="#35245E",
            expression=FaceExpression.CURIOUS,
            accent=VisualAccent.CURIOUS,
            reaction_strength=0.55,
        )
    if state is RobotState.SPEAKING:
        return FaceState(
            background="#164F3B",
            expression=FaceExpression.HAPPY,
            accent=VisualAccent.WARM,
            reaction_strength=0.55,
        )
    if state is RobotState.SLEEPING:
        return FaceState(
            background="#08101E",
            expression=FaceExpression.SLEEPY,
            accent=VisualAccent.SLEEPY,
            reaction_strength=1.0,
        )
    if state is RobotState.ERROR:
        return FaceState(
            background="#6B1D2A",
            expression=FaceExpression.WORRIED,
            accent=VisualAccent.ERROR,
            reaction_strength=0.80,
        )
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


def _visual_reaction(
    label: object, confidence: float
) -> Optional[tuple[FaceExpression, VisualAccent, float]]:
    """React to useful semantic observations; UNKNOWN allows normal decay."""
    if not isinstance(label, str) or not math.isfinite(confidence) or confidence <= 0:
        return None
    bounded_confidence = max(0.0, min(confidence, 1.0))
    if label in {"happy", "happiness"}:
        return FaceExpression.HAPPY, VisualAccent.WARM, min(0.90, bounded_confidence)
    if label in {"surprised", "surprise"}:
        return FaceExpression.SURPRISED, VisualAccent.ALERT, min(0.90, bounded_confidence)
    if label == "neutral":
        return FaceExpression.NEUTRAL, VisualAccent.NEUTRAL, min(0.25, bounded_confidence * 0.30)
    return None
