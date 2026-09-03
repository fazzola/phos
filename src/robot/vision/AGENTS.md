# PHOS Vision Instructions

Applies to camera, face detection and facial-expression observation.

## Pipeline
Preserve the conceptual pipeline:
`CameraProvider → FaceDetector → ExpressionProvider → ExpressionSmoother → provider-neutral Vision observation/event`.

## Raspberry Pi target
- Prefer Picamera2 for Raspberry Pi Camera capture; do not substitute `cv2.VideoCapture` for the Pi camera path without an approved reason.
- Prefer OpenCV for lightweight preprocessing/detection.
- A Haar Cascade is acceptable for the first lightweight face detector.
- Prefer OpenCV DNN with a lightweight configurable ONNX model for expression classification.
- Do not add TensorFlow/PyTorch runtime on Raspberry Pi 3 without explicit justification/approval.
- Detection/inference frequency must be independent from display rendering frequency; do not infer every frame.

## Semantics and privacy
- Facial-expression output is an uncertain visual observation, not a claim about a person's true emotion or mental state.
- Use confidence/smoothing and handle no-face, low-confidence, face-lost and unstable observations.
- Do not implement identity recognition or biometric persistence.
- Do not save frames or face crops by default.

## Boundaries
- Vision must not call the LLM directly.
- Vision must not control the eye renderer directly.
- Prefer `Vision → Robot state/event/context → BehaviorEngine`.
- Keep model path, labels and input dimensions configurable because they are model-specific.
