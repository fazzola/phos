"""Pure, interpolated eye geometry for the PHOS face."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from .state import BlinkPhase, FaceExpression, FaceState


@dataclass(frozen=True)
class EyeGeometry:
    center_x: float
    center_y: float
    radius_x: float
    radius_y: float
    pupil_x: float
    pupil_y: float
    pupil_radius: float
    squint: float
    closed: bool


@dataclass(frozen=True)
class EyeFrame:
    width: int
    height: int
    background: str
    eyes: Tuple[EyeGeometry, EyeGeometry]


@dataclass
class _AnimatedValues:
    eye_open_left: float
    eye_open_right: float
    squint: float
    pupil_x: float
    pupil_y: float


class EyeRenderer:
    """Convert only ``FaceState`` into smoothly animated eye geometry."""

    def __init__(self, *, width: int = 800, height: int = 600, transition_seconds: float = 0.18) -> None:
        if width <= 0 or height <= 0 or transition_seconds <= 0:
            raise ValueError("Eye renderer dimensions and transition duration must be positive.")
        self._width = width
        self._height = height
        self._transition_seconds = transition_seconds
        self._values: Optional[_AnimatedValues] = None
        self._last_timestamp: Optional[float] = None

    def render(self, face_state: FaceState, *, timestamp: float) -> EyeFrame:
        state = face_state.normalized()
        target = _target_values(state)
        if self._values is None:
            self._values = target
        else:
            previous_timestamp = timestamp if self._last_timestamp is None else self._last_timestamp
            elapsed = max(0.0, timestamp - previous_timestamp)
            self._values = _interpolate(self._values, target, min(elapsed / self._transition_seconds, 1.0))
        self._last_timestamp = timestamp
        blink_amount = _blink_openness(state.blink_phase, state.blink_progress)
        return EyeFrame(
            width=self._width,
            height=self._height,
            background=state.background,
            eyes=(
                self._make_eye(True, blink_amount, self._values),
                self._make_eye(False, blink_amount, self._values),
            ),
        )

    def _make_eye(self, left: bool, blink_amount: float, values: _AnimatedValues) -> EyeGeometry:
        eye_width = self._width * 0.27
        base_height = self._height * 0.42
        separation = self._width * 0.16
        center_x = self._width / 2 - separation if left else self._width / 2 + separation
        center_y = self._height * 0.50
        radius_x = eye_width / 2
        openness = values.eye_open_left if left else values.eye_open_right
        visible_open = max(0.0, openness * (1.0 - values.squint * 0.40) * blink_amount)
        radius_y = max(2.0, base_height * visible_open / 2)
        pupil_radius = max(7.0, min(radius_x, radius_y) * 0.26)
        max_pupil_x = max(0.0, radius_x * 0.52 - pupil_radius)
        max_pupil_y = max(0.0, radius_y * 0.52 - pupil_radius)
        return EyeGeometry(
            center_x=center_x,
            center_y=center_y,
            radius_x=radius_x,
            radius_y=radius_y,
            pupil_x=center_x + values.pupil_x * max_pupil_x,
            pupil_y=center_y + values.pupil_y * max_pupil_y,
            pupil_radius=pupil_radius,
            squint=values.squint,
            closed=blink_amount <= 0.02,
        )


def _target_values(state: FaceState) -> _AnimatedValues:
    profile = _expression_profile(state.expression)
    strength = state.reaction_strength
    base_open = _blend(state.eye_open, profile[0], strength)
    asymmetry = profile[1] * strength
    return _AnimatedValues(
        eye_open_left=max(0.0, base_open - asymmetry),
        eye_open_right=max(0.0, base_open + asymmetry),
        squint=_blend(state.squint, profile[2], strength),
        pupil_x=_clamp_unit(state.pupil_x + profile[3] * strength),
        pupil_y=_clamp_unit(state.pupil_y + profile[4] * strength),
    )


def _expression_profile(expression: FaceExpression) -> Tuple[float, float, float, float, float]:
    if expression is FaceExpression.HAPPY:
        return (0.90, 0.0, 0.30, 0.0, 0.10)
    if expression is FaceExpression.CURIOUS:
        return (1.0, 0.10, 0.08, 0.12, -0.08)
    if expression is FaceExpression.SURPRISED:
        return (1.18, 0.0, 0.0, 0.0, -0.04)
    if expression is FaceExpression.SLEEPY:
        return (0.38, 0.0, 0.36, 0.0, 0.10)
    if expression is FaceExpression.WORRIED:
        return (0.82, 0.04, 0.18, -0.10, -0.08)
    return (1.0, 0.0, 0.05, 0.0, 0.0)


def _interpolate(current: _AnimatedValues, target: _AnimatedValues, amount: float) -> _AnimatedValues:
    return _AnimatedValues(
        eye_open_left=_blend(current.eye_open_left, target.eye_open_left, amount),
        eye_open_right=_blend(current.eye_open_right, target.eye_open_right, amount),
        squint=_blend(current.squint, target.squint, amount),
        pupil_x=_blend(current.pupil_x, target.pupil_x, amount),
        pupil_y=_blend(current.pupil_y, target.pupil_y, amount),
    )


def _blink_openness(phase: BlinkPhase, progress: float) -> float:
    if phase is BlinkPhase.CLOSING:
        return 1.0 - progress
    if phase is BlinkPhase.CLOSED:
        return 0.0
    if phase is BlinkPhase.OPENING:
        return progress
    return 1.0


def _blend(start: float, end: float, amount: float) -> float:
    return start + (end - start) * amount


def _clamp_unit(value: float) -> float:
    return max(-1.0, min(value, 1.0))
