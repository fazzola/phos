"""Provider-neutral local vision pipeline for PHOS."""

from .camera import Picamera2CameraProvider
from .detector import OpenCVFaceDetector
from .expression import OpenCVExpressionProvider
from .pipeline import (
    VISION_EXPRESSION_STABLE,
    VISION_FACE_LOST,
    VISION_FACE_POSITION,
    VisionPipeline,
    VisionResult,
    VisionStatus,
    crop_face,
    face_position,
)
from .provider import (
    CameraProvider,
    ExpressionObservation,
    ExpressionProvider,
    FaceDetector,
    FacePosition,
    FaceRegion,
    VisualExpression,
)
from .smoother import ExpressionSmoother

__all__ = [
    "CameraProvider",
    "ExpressionObservation",
    "ExpressionProvider",
    "ExpressionSmoother",
    "FaceDetector",
    "FacePosition",
    "FaceRegion",
    "OpenCVExpressionProvider",
    "OpenCVFaceDetector",
    "Picamera2CameraProvider",
    "VISION_EXPRESSION_STABLE",
    "VISION_FACE_LOST",
    "VISION_FACE_POSITION",
    "VisionPipeline",
    "VisionResult",
    "VisionStatus",
    "VisualExpression",
    "crop_face",
    "face_position",
]
