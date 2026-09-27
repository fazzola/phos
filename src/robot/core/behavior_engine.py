"""Behavior decisions that produce FaceState without drawing UI elements."""

from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from dataclasses import replace
from typing import Callable, Optional

from robot.ui.state import AmbientOverlayState, BlinkPhase, EnvironmentalLEDIntent, FaceExpression, FaceState, VisualAccent
from robot.motion import MotionState

from .behaviors import Behavior
from .events import Event, EventBus
from .runtime import STATE_CHANGED
from .state import RobotState
from .environmental import EnvironmentalState

logger = logging.getLogger(__name__)

VISION_EXPRESSION_STABLE = "vision.visual_expression_stable"
VISION_FACE_LOST = "vision.face_lost"
VISION_FACE_POSITION = "vision.face_position"
IMU_MOTION_STATE = "imu.motion_state"
ENVIRONMENTAL_STATE_CHANGED = "environmental.state_changed"

_MOTION_TILT_OFFSETS = {
    # pupil_x/pupil_y factor, base openness, left-eye asymmetry factor
    MotionState.TILT_LEFT: (-1.0, 0.0, 1.12, 1.0),
    MotionState.TILT_RIGHT: (1.0, 0.0, 1.12, -1.0),
    MotionState.TILT_FORWARD: (0.0, -1.0, 1.23, 0.0),
    MotionState.TILT_BACK: (0.0, 1.0, .82, 0.0),
}


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
        imu_reaction_strength: float = .90,
        imu_tilt_gaze_strength: float = .86,
        imu_tilt_eye_asymmetry_strength: float = .18,
        imu_shake_reaction_strength: float = .88,
        imu_impact_reaction_strength: float = 1.0,
        imu_shake_reaction_duration_seconds: float = 1.35,
        imu_impact_reaction_duration_seconds: float = 1.0,
        imu_reaction_cooldown_seconds: float = 2.0,
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
        self.configure_imu_reactions(imu_reaction_strength, imu_tilt_gaze_strength, imu_tilt_eye_asymmetry_strength,
                                     imu_shake_reaction_strength, imu_impact_reaction_strength,
                                     imu_shake_reaction_duration_seconds, imu_impact_reaction_duration_seconds,
                                     imu_reaction_cooldown_seconds)
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
        self._motion_state = MotionState.STILL
        self._motion_state_started_at = float("-inf")
        self._motion_transient = None
        self._motion_last_at = float("-inf")
        self._environmental_state = EnvironmentalState.NORMAL
        # Standalone engine users retain historical environmental behavior;
        # application construction always supplies canonical configuration.
        self._base_visual_source = "environment"
        self._environment_overlays_enabled = True
        self._unsubscribers: list[Callable[[], None]] = []
        self._task: Optional[asyncio.Task[None]] = None

    @property
    def face_state(self) -> FaceState:
        state = replace(
            self._state,
            blink_phase=self._blink_phase,
            blink_progress=self._blink_progress(self._clock()),
        )
        return self._with_motion_reaction(state, self._clock()).normalized()

    @property
    def base_visual_source(self) -> str:
        """Current semantic source; adapters must not inspect renderer state."""
        return self._base_visual_source

    def configure_imu_reactions(self, strength, tilt_gaze_strength, tilt_eye_asymmetry_strength,
                                shake_strength, impact_strength,
                                shake_duration, impact_duration, cooldown):
        if not all(0 <= value <= 1 for value in (strength, tilt_gaze_strength, shake_strength, impact_strength)):
            raise ValueError("IMU reaction strengths must be between zero and one")
        if not 0 <= tilt_eye_asymmetry_strength <= .5:
            raise ValueError("IMU tilt eye asymmetry strength must be between zero and 0.5")
        if impact_strength <= shake_strength:
            raise ValueError("IMU impact reaction strength must exceed shake reaction strength")
        if shake_duration <= 0 or impact_duration <= 0 or cooldown < 0:
            raise ValueError("IMU reaction durations/cooldown are invalid")
        self._imu_reaction_strength = strength
        self._imu_tilt_gaze_strength = tilt_gaze_strength
        self._imu_tilt_eye_asymmetry_strength = tilt_eye_asymmetry_strength
        self._imu_shake_strength = shake_strength
        self._imu_impact_strength = impact_strength
        self._imu_shake_duration = shake_duration
        self._imu_impact_duration = impact_duration
        self._imu_cooldown = cooldown

    def configure_base_visual_source(self, source):
        if source not in {"manual", "environment", "state"}:
            raise ValueError("Unsupported base visual source")
        self._base_visual_source = source

    def configure_environment_overlays(self, enabled):
        self._environment_overlays_enabled = bool(enabled)
        if not self._environment_overlays_enabled:
            self._state = replace(self._state, ambient_overlay=AmbientOverlayState())

    async def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("Behavior engine is already running.")
        self._unsubscribers = [
            self._events.subscribe(STATE_CHANGED, self._on_robot_state),
            self._events.subscribe(VISION_EXPRESSION_STABLE, self._on_visual_expression),
            self._events.subscribe(VISION_FACE_POSITION, self._on_face_position),
            self._events.subscribe(VISION_FACE_LOST, self._on_face_lost),
            self._events.subscribe(IMU_MOTION_STATE, self._on_motion_state),
            self._events.subscribe(ENVIRONMENTAL_STATE_CHANGED, self._on_environmental_state),
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

    async def _on_motion_state(self, event: Event) -> None:
        try:
            state = MotionState(event.data["state"])
        except (KeyError, ValueError, TypeError):
            return
        if state is not self._motion_state:
            self._motion_state_started_at = self._clock()
        self._motion_state = state
        if state not in {MotionState.SHAKE, MotionState.IMPACT}:
            if state is MotionState.MOVING:
                logger.debug("IMU behavior state=moving gaze=(0.00,0.00) eye_open=1.16 strength=%.2f",
                             self._imu_reaction_strength * .70)
            elif state in _MOTION_TILT_OFFSETS:
                x, y, eye_open, eye_factor = _MOTION_TILT_OFFSETS[state]
                asymmetry = eye_factor * self._imu_tilt_eye_asymmetry_strength
                logger.debug("IMU behavior state=%s gaze=(%.2f,%.2f) eye_open=%.2f asymmetry=%.2f strength=%.2f",
                             state.value, x * self._imu_tilt_gaze_strength, y * self._imu_tilt_gaze_strength,
                             eye_open, asymmetry, self._imu_reaction_strength * .62)
            else:
                logger.debug("IMU behavior state=%s", state.value)
            return
        now = self._clock()
        if now - self._motion_last_at < self._imu_cooldown:
            return
        self._motion_last_at = now
        self._motion_transient = (state, now)
        logger.debug("IMU behavior transient=%s strength=%.2f duration=%.2fs", state.value,
                     self._imu_shake_strength if state is MotionState.SHAKE else self._imu_impact_strength,
                     self._imu_shake_duration if state is MotionState.SHAKE else self._imu_impact_duration)

    async def _on_environmental_state(self, event: Event) -> None:
        try:
            self._environmental_state = EnvironmentalState(event.data["state"])
            self._state = replace(self._state, ambient_overlay=AmbientOverlayState(
                event.data.get("temperature_overlay", "none"), event.data.get("air_quality_overlay", "none"))
                if self._environment_overlays_enabled else AmbientOverlayState())
        except (KeyError, TypeError, ValueError):
            return

    def _with_motion_reaction(self, state: FaceState, now: float) -> FaceState:
        """Apply IMU intent only below RobotState priority, without UI geometry."""
        if self._robot_state is not RobotState.IDLE:
            return replace(state, motion_state=None, motion_event_at=None)
        state = self._resolve_persistent_visual_state(state)
        transient = self._motion_transient
        if transient is not None:
            kind, started_at = transient
            duration = self._imu_shake_duration if kind is MotionState.SHAKE else self._imu_impact_duration
            elapsed = max(0.0, now - started_at)
            if elapsed >= duration:
                self._motion_transient = None
            else:
                hold = duration * .55
                peak_strength = self._imu_shake_strength if kind is MotionState.SHAKE else self._imu_impact_strength
                strength = peak_strength if elapsed <= hold else peak_strength * (duration - elapsed) / (duration - hold)
                eye_open = 1.18 if kind is MotionState.SHAKE else 1.25
                lateral = .68 if kind is MotionState.SHAKE else -.76
                return replace(state, eye_open=eye_open, pupil_x=lateral, pupil_y=-.18,
                               eye_asymmetry=0.0,
                               expression=FaceExpression.SURPRISED, accent=VisualAccent.ALERT,
                               reaction_strength=max(state.reaction_strength, strength),
                               motion_state=kind.value, motion_event_at=started_at, motion_started_at=started_at)
        if self._motion_state is MotionState.MOVING:
            return replace(state, eye_open=max(state.eye_open, 1.16), eye_asymmetry=0.0, pupil_x=0.0, pupil_y=0.0,
                           expression=FaceExpression.CURIOUS,
                           reaction_strength=max(state.reaction_strength, self._imu_reaction_strength * .70),
                           motion_state=self._motion_state.value, motion_started_at=self._motion_state_started_at)
        gaze = self._imu_tilt_gaze_strength
        if self._motion_state in _MOTION_TILT_OFFSETS:
            x_factor, y_factor, openness, eye_factor = _MOTION_TILT_OFFSETS[self._motion_state]
            x, y = x_factor * gaze, y_factor * gaze
            asymmetry = eye_factor * self._imu_tilt_eye_asymmetry_strength
            return replace(state, pupil_x=x, pupil_y=y, eye_open=max(state.eye_open, openness) if openness >= 1 else min(state.eye_open, openness),
                           eye_asymmetry=asymmetry,
                           expression=FaceExpression.CURIOUS, accent=VisualAccent.CURIOUS,
                           reaction_strength=max(state.reaction_strength, self._imu_reaction_strength * .62),
                           motion_state=self._motion_state.value, motion_started_at=self._motion_state_started_at)
        return replace(state, motion_state=self._motion_state.value, motion_event_at=None,
                       motion_started_at=self._motion_state_started_at)

    def _resolve_persistent_visual_state(self, state: FaceState) -> FaceState:
        """Persistent context, below transient motion and above Vision intent."""
        if self._base_visual_source == "manual":
            return replace(state, expression=FaceExpression.NEUTRAL, accent=VisualAccent.NEUTRAL,
                           environmental_led_intent=None, reaction_strength=0.0)
        if self._base_visual_source == "state":
            return replace(state, environmental_led_intent=None)
        if self._environmental_state is EnvironmentalState.COLD:
            return replace(state, eye_open=max(state.eye_open, 1.10), expression=FaceExpression.CURIOUS,
                           accent=VisualAccent.COOL, environmental_led_intent=EnvironmentalLEDIntent.COLD,
                           reaction_strength=max(state.reaction_strength, .45))
        if self._environmental_state is EnvironmentalState.WARM:
            return replace(state, eye_open=min(state.eye_open, .88), expression=FaceExpression.SLEEPY,
                           accent=VisualAccent.WARM, environmental_led_intent=EnvironmentalLEDIntent.WARM,
                           reaction_strength=max(state.reaction_strength, .45))
        if self._environmental_state is EnvironmentalState.AIR_QUALITY_WARNING:
            return replace(state, eye_open=max(state.eye_open, 1.12), expression=FaceExpression.CURIOUS,
                           accent=VisualAccent.ALERT, environmental_led_intent=EnvironmentalLEDIntent.AIR_QUALITY_WARNING,
                           reaction_strength=max(state.reaction_strength, .62))
        if self._environmental_state is EnvironmentalState.AIR_QUALITY_BAD:
            return replace(state, eye_open=max(state.eye_open, 1.20), expression=FaceExpression.SURPRISED,
                           accent=VisualAccent.ALERT, environmental_led_intent=EnvironmentalLEDIntent.AIR_QUALITY_BAD,
                           reaction_strength=max(state.reaction_strength, .82))
        return state

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
