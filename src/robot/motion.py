"""Lightweight, provider-neutral interpretation of IMU samples."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from robot.sensors import IMUReading


class MotionState(str, Enum):
    STILL = "still"
    MOVING = "moving"
    TILT_LEFT = "tilt_left"
    TILT_RIGHT = "tilt_right"
    TILT_FORWARD = "tilt_forward"
    TILT_BACK = "tilt_back"
    SHAKE = "shake"
    IMPACT = "impact"


@dataclass(frozen=True)
class MotionSettings:
    movement_threshold_m_s2: float
    tilt_threshold_m_s2: float
    shake_threshold_deg_s: float
    impact_threshold_m_s2: float
    confirmation_seconds: float
    cooldown_seconds: float


@dataclass(frozen=True)
class MotionEvent:
    state: MotionState
    at_monotonic: float


class MotionInterpreter:
    """Classify filtered samples without device access or orientation fusion."""

    _FILTER_ALPHA = .25
    _STANDARD_GRAVITY = 9.80665

    def __init__(self, settings: MotionSettings):
        self.configure(settings)
        self._filtered_acceleration = None
        self._state = MotionState.STILL
        self._candidate = None
        self._candidate_since = None
        self._last_event_at = float("-inf")
        self._last_spin = None

    @property
    def state(self):
        return self._state

    def configure(self, settings: MotionSettings):
        self._settings = settings

    @staticmethod
    def _magnitude(values):
        return math.sqrt(sum(value * value for value in values))

    def _filtered(self, reading):
        sample = (reading.acceleration_x_m_s2, reading.acceleration_y_m_s2, reading.acceleration_z_m_s2)
        if self._filtered_acceleration is None:
            self._filtered_acceleration = sample
        else:
            alpha = self._FILTER_ALPHA
            self._filtered_acceleration = tuple(alpha * value + (1 - alpha) * old
                                                for value, old in zip(sample, self._filtered_acceleration))
        return self._filtered_acceleration

    def _shake(self, reading, now):
        gyros = (reading.angular_velocity_x_deg_s, reading.angular_velocity_y_deg_s,
                 reading.angular_velocity_z_deg_s)
        axis = max(range(3), key=lambda index: abs(gyros[index]))
        value = gyros[axis]
        if abs(value) < self._settings.shake_threshold_deg_s:
            return False
        current = (axis, 1 if value > 0 else -1, now)
        previous, self._last_spin = self._last_spin, current
        return previous is not None and previous[0] == axis and previous[1] != current[1] and now - previous[2] <= 2.0

    def _classify(self, reading, now):
        acceleration = self._filtered(reading)
        magnitude = self._magnitude(acceleration)
        raw_magnitude = self._magnitude((reading.acceleration_x_m_s2, reading.acceleration_y_m_s2,
                                         reading.acceleration_z_m_s2))
        if raw_magnitude >= self._settings.impact_threshold_m_s2:
            return MotionState.IMPACT
        if self._shake(reading, now):
            return MotionState.SHAKE
        x, y, _z = acceleration
        if abs(magnitude - self._STANDARD_GRAVITY) <= self._settings.movement_threshold_m_s2:
            if x <= -self._settings.tilt_threshold_m_s2:
                return MotionState.TILT_LEFT
            if x >= self._settings.tilt_threshold_m_s2:
                return MotionState.TILT_RIGHT
            if y >= self._settings.tilt_threshold_m_s2:
                return MotionState.TILT_FORWARD
            if y <= -self._settings.tilt_threshold_m_s2:
                return MotionState.TILT_BACK
            return MotionState.STILL
        return MotionState.MOVING

    def observe(self, reading: IMUReading, now: float) -> tuple[MotionState, MotionEvent | None]:
        """Return a debounced state and, at most, one cooldown-limited event."""
        candidate = self._classify(reading, now)
        if candidate is MotionState.IMPACT:
            self._candidate = None
            self._candidate_since = None
            self._state = candidate
            return self._event(candidate, now)
        # An opposite high-rate pair is its own temporal confirmation.
        if candidate is MotionState.SHAKE:
            self._candidate = None
            self._candidate_since = None
            self._state = candidate
            return self._event(candidate, now)
        if candidate is not self._candidate:
            self._candidate, self._candidate_since = candidate, now
            return self._state, None
        if candidate is not self._state and now - self._candidate_since >= self._settings.confirmation_seconds:
            self._state = candidate
            return self._event(candidate, now)
        return self._state, None

    def _event(self, state, now):
        if now - self._last_event_at < self._settings.cooldown_seconds:
            return state, None
        self._last_event_at = now
        return state, MotionEvent(state, now)


def tilt_direction(state: MotionState) -> str | None:
    return state.value if state in {MotionState.TILT_LEFT, MotionState.TILT_RIGHT,
                                    MotionState.TILT_FORWARD, MotionState.TILT_BACK} else None
