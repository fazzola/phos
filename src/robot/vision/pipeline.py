"""Rate-limited local vision orchestration, independent of LLMs and hardware SDKs."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from robot.core import Behavior, Event, EventBus

from .provider import CameraProvider, ExpressionProvider, FaceDetector, FacePosition, FaceRegion, VisualExpression
from .smoother import ExpressionSmoother

VISION_EXPRESSION_STABLE = "vision.visual_expression_stable"
VISION_FACE_LOST = "vision.face_lost"
VISION_FACE_POSITION = "vision.face_position"


class VisionStatus(str, Enum):
    NOT_DUE = "not_due"
    NO_FACE = "no_face"
    LOW_CONFIDENCE = "low_confidence"
    UNSTABLE = "unstable"
    STABLE = "stable"
    FACE_DETECTED = "face_detected"


@dataclass(frozen=True)
class VisionResult:
    status: VisionStatus
    visual_expression: Optional[VisualExpression] = None


class VisionPipeline(Behavior):
    """Capture, detect, classify, smooth and publish local vision results."""

    name = "vision-pipeline"

    def __init__(
        self,
        camera: CameraProvider,
        face_detector: FaceDetector,
        expression_provider: Optional[ExpressionProvider],
        smoother: Optional[ExpressionSmoother],
        *,
        events: Optional[EventBus] = None,
        capture_interval_seconds: float = 1.0 / 15.0,
        detection_interval_seconds: float = 1.0 / 4.0,
        expression_interval_seconds: float = 1.0 / 3.0,
    ) -> None:
        for name, value in (
            ("capture_interval_seconds", capture_interval_seconds),
            ("detection_interval_seconds", detection_interval_seconds),
            ("expression_interval_seconds", expression_interval_seconds),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive.")
        if (expression_provider is None) != (smoother is None):
            raise ValueError("expression_provider and smoother must be configured together.")
        self._camera = camera
        self._face_detector = face_detector
        self._expression_provider = expression_provider
        self._smoother = smoother
        self._events = events
        self._capture_interval = capture_interval_seconds
        self._detection_interval = detection_interval_seconds
        self._expression_interval = expression_interval_seconds
        self._next_detection_at = 0.0
        self._next_expression_at = 0.0
        self._face_present = False
        self._last_published_label: Optional[str] = None
        self._task: Optional[asyncio.Task[None]] = None

    async def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("Vision pipeline is already running.")
        await self._camera.start()
        self._task = asyncio.create_task(self._run(), name="vision-pipeline")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:
                # A runtime supervisor observes and reports task failures. Stop
                # must still release the camera after such a failure.
                pass
            self._task = None
        await self._camera.stop()

    async def wait(self) -> None:
        """Wait for the background pipeline task; used by the runtime supervisor."""
        if self._task is None:
            raise RuntimeError("Vision pipeline is not running.")
        await asyncio.shield(self._task)

    async def process_once(self, *, timestamp: Optional[float] = None) -> VisionResult:
        """Capture one frame and perform work only when its rate limit permits."""
        now = time.monotonic() if timestamp is None else timestamp
        frame = await self._camera.capture_frame()
        if now < self._next_detection_at:
            return VisionResult(VisionStatus.NOT_DUE)
        self._next_detection_at = now + self._detection_interval
        faces = await self._face_detector.detect(frame)
        face = _select_largest_face(faces)
        if face is None:
            if self._smoother is not None:
                self._smoother.reset()
            self._last_published_label = None
            if self._face_present and self._events is not None:
                await self._events.publish(Event(VISION_FACE_LOST))
            self._face_present = False
            return VisionResult(VisionStatus.NO_FACE)

        self._face_present = True
        if self._events is not None:
            position = face_position(frame, face)
            await self._events.publish(
                Event(VISION_FACE_POSITION, {"face_position": {"x": position.x, "y": position.y}})
            )
        if self._expression_provider is None or self._smoother is None:
            return VisionResult(VisionStatus.FACE_DETECTED)
        if now < self._next_expression_at:
            return VisionResult(VisionStatus.NOT_DUE)
        self._next_expression_at = now + self._expression_interval
        face_crop = crop_face(frame, face)
        if face_crop is None:
            self._smoother.reset()
            return VisionResult(VisionStatus.NO_FACE)
        observation = await self._expression_provider.classify(face_crop)
        if observation is None or observation.confidence < self._smoother.minimum_confidence:
            self._smoother.reset()
            return VisionResult(VisionStatus.LOW_CONFIDENCE)

        stable = self._smoother.observe(observation, timestamp=now)
        if stable is None:
            return VisionResult(VisionStatus.UNSTABLE)
        if stable.label != self._last_published_label and self._events is not None:
            await self._events.publish(
                Event(
                    VISION_EXPRESSION_STABLE,
                    {
                        "visual_expression": {
                            "label": stable.label,
                            "confidence": stable.confidence,
                            "observed_for_ms": stable.observed_for_ms,
                        }
                    },
                )
            )
        self._last_published_label = stable.label
        return VisionResult(VisionStatus.STABLE, stable)

    async def _run(self) -> None:
        while True:
            await self.process_once()
            await asyncio.sleep(self._capture_interval)


def _select_largest_face(faces: Any) -> Optional[FaceRegion]:
    return max(faces, key=lambda face: face.area, default=None)


def crop_face(frame: Any, face: FaceRegion) -> Optional[Any]:
    """Return a bounds-checked image slice without copying the face crop."""
    shape = getattr(frame, "shape", None)
    if not shape or len(shape) < 2:
        raise ValueError("Camera frames must expose image-like shape information.")
    frame_height, frame_width = int(shape[0]), int(shape[1])
    left = max(face.x, 0)
    top = max(face.y, 0)
    right = min(face.x + face.width, frame_width)
    bottom = min(face.y + face.height, frame_height)
    if left >= right or top >= bottom:
        return None
    return frame[top:bottom, left:right]


def face_position(frame: Any, face: FaceRegion) -> FacePosition:
    """Map a detected face center to bounded, UI-neutral camera coordinates."""
    shape = getattr(frame, "shape", None)
    if not shape or len(shape) < 2:
        raise ValueError("Camera frames must expose image-like shape information.")
    frame_height, frame_width = int(shape[0]), int(shape[1])
    if frame_width <= 0 or frame_height <= 0:
        raise ValueError("Camera frame dimensions must be positive.")
    center_x = face.x + face.width / 2
    center_y = face.y + face.height / 2
    return FacePosition(
        x=_clamp_unit(center_x / (frame_width / 2) - 1.0),
        y=_clamp_unit(center_y / (frame_height / 2) - 1.0),
    )


def _clamp_unit(value: float) -> float:
    return max(-1.0, min(value, 1.0))
