"""Provider-neutral local vision pipeline for PHOS."""

from .camera import Picamera2CameraProvider
from .detector import OpenCVFaceDetector
from .expression import OpenCVExpressionProvider
from .pipeline import (
    VISION_EXPRESSION_STABLE,
    VISION_FACE_LOST,
    VisionPipeline,
    VisionResult,
    VisionStatus,
    crop_face,
)
from .provider import (
    CameraProvider,
    ExpressionObservation,
    ExpressionProvider,
    FaceDetector,
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
    "FaceRegion",
    "OpenCVExpressionProvider",
    "OpenCVFaceDetector",
    "Picamera2CameraProvider",
    "VISION_EXPRESSION_STABLE",
    "VISION_FACE_LOST",
    "VisionPipeline",
    "VisionResult",
    "VisionStatus",
    "VisualExpression",
    "crop_face",
]
