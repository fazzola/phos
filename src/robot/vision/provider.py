"""Provider-neutral contracts and data structures for visual perception."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional, Sequence, Tuple


@dataclass(frozen=True)
class FaceRegion:
    """A rectangular face location in pixels within a captured frame."""

    x: int
    y: int
    width: int
    height: int

    @property
    def area(self) -> int:
        return self.width * self.height


@dataclass(frozen=True)
class FacePosition:
    """The center of a detected face, normalized to the camera frame."""

    x: float
    y: float


@dataclass(frozen=True)
class ExpressionObservation:
    """Raw model output; labelled probabilities enable semantic abstention."""

    label: str
    confidence: float
    probabilities: Tuple[Tuple[str, float], ...] = ()


@dataclass(frozen=True)
class VisualExpression:
    """A confirmed semantic observation, or explicit UNKNOWN abstention."""

    label: str
    confidence: float
    observed_for_ms: int


class CameraProvider(ABC):
    """Camera lifecycle and frame capture boundary."""

    @abstractmethod
    async def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def capture_frame(self) -> Any:
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> None:
        raise NotImplementedError


class FaceDetector(ABC):
    """Detect visible faces without exposing a computer-vision backend."""

    @abstractmethod
    async def detect(self, frame: Any) -> Sequence[FaceRegion]:
        raise NotImplementedError


class ExpressionProvider(ABC):
    """Classify visible features in a cropped face image."""

    @abstractmethod
    async def classify(self, face_crop: Any) -> Optional[ExpressionObservation]:
        raise NotImplementedError
