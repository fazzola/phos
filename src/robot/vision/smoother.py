"""Temporal smoothing for uncertain visible-expression observations."""

from __future__ import annotations

import time
from typing import Optional

from .provider import ExpressionObservation, VisualExpression


class ExpressionSmoother:
    """Require several timely, confident observations before reporting a label."""

    def __init__(
        self,
        *,
        minimum_confidence: float = 0.60,
        minimum_observations: int = 3,
        maximum_gap_seconds: float = 1.5,
    ) -> None:
        if not 0.0 <= minimum_confidence <= 1.0:
            raise ValueError("minimum_confidence must be between 0.0 and 1.0.")
        if minimum_observations < 1:
            raise ValueError("minimum_observations must be at least one.")
        if maximum_gap_seconds <= 0:
            raise ValueError("maximum_gap_seconds must be positive.")
        self.minimum_confidence = minimum_confidence
        self._minimum_observations = minimum_observations
        self._maximum_gap_seconds = maximum_gap_seconds
        self._label: Optional[str] = None
        self._started_at: Optional[float] = None
        self._last_at: Optional[float] = None
        self._confidences: list[float] = []

    def observe(
        self, observation: ExpressionObservation, *, timestamp: Optional[float] = None
    ) -> Optional[VisualExpression]:
        now = time.monotonic() if timestamp is None else timestamp
        if observation.confidence < self.minimum_confidence:
            self.reset()
            return None
        if self._should_reset(observation.label, now):
            self._label = observation.label
            self._started_at = now
            self._confidences = []
        self._last_at = now
        self._confidences.append(observation.confidence)
        if len(self._confidences) < self._minimum_observations:
            return None
        return VisualExpression(
            label=self._label,
            confidence=sum(self._confidences) / len(self._confidences),
            observed_for_ms=int((now - self._started_at) * 1000),
        )

    def reset(self) -> None:
        self._label = None
        self._started_at = None
        self._last_at = None
        self._confidences = []

    def _should_reset(self, label: str, now: float) -> bool:
        return (
            self._label != label
            or self._last_at is None
            or now - self._last_at > self._maximum_gap_seconds
        )
