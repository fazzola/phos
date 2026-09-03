# Vision

## Goal

Add local visual perception using Raspberry Pi Camera while keeping the
application independent from Picamera2, OpenCV and any specific ML model.

The system classifies **visible facial expressions**. It must not claim to
know a person's true internal emotional state.

## Architecture

```text
Raspberry Pi Camera
        |
        v
  CameraProvider
        |
        v
   FaceDetector
        |
        v
 ExpressionProvider
        |
        v
 temporal smoothing
        |
        v
    Robot Core
```

## CameraProvider

Initial implementation: `Picamera2CameraProvider`.

Default target:
- 640x480 RGB
- Picamera2 hidden behind the provider abstraction
- capture frequency may be higher than inference frequency

## FaceDetector

Initial implementation: `OpenCVFaceDetector`.

Start with OpenCV Haar Cascade because it is lightweight enough for a
Raspberry Pi 3. A DNN detector may replace it later without changing callers.

## ExpressionProvider

Initial implementation: `OpenCVExpressionProvider`.

Use an ONNX model loaded through `cv2.dnn.readNetFromONNX`.

Typical labels may include:
- angry
- disgusted
- fearful
- happy
- sad
- surprised
- neutral

Exact labels depend on the selected ONNX model and must stay configurable.

## Raspberry Pi 3 performance policy

Do not run expression inference for every camera frame.

Suggested initial targets:
- camera capture/preview: up to 15-30 FPS when useful
- face detection: about 3-5 FPS
- expression inference: about 2-5 FPS

Prefer cropping the face and resizing it to a small model input such as
64x64 or 96x96.

Avoid full PyTorch/TensorFlow runtimes on Raspberry Pi 3 unless a concrete
need justifies them. Prefer OpenCV DNN + ONNX.

## Temporal smoothing

The robot must not react to one isolated prediction.

Aggregate several observations and apply a minimum confidence before
publishing a stable result.

Example:

```yaml
visual_expression:
  label: happy
  confidence: 0.78
  observed_for_ms: 1800
```

## Semantics

Facial-expression classifiers are uncertain visual observations.

Prefer:
- "the visible expression appears positive"
- "happy-like expression detected"

Avoid:
- "the person is happy"
- psychological conclusions based solely on facial appearance

## AI integration

Vision must not invoke the LLM directly.

Preferred flow:

```text
Vision -> Robot Event/State -> Agent context
```

Simple UI/behavior reactions should be possible without involving the LLM.

## Initial implementation

`VisionPipeline` is the lifecycle-managed service implementing this flow. It
captures RGB frames in memory, rate-limits Haar face detection and ONNX
expression inference independently, then publishes only stable observations as
`vision.visual_expression_stable`. The event payload contains
`visual_expression.label`, `confidence`, and `observed_for_ms`; it does not
make a claim about internal emotional state.

The default Pi adapter uses `Picamera2CameraProvider` at 640x480. Install
optional vision dependencies with `pip install '.[vision]'`; the ONNX model is
external and its path, labels, input size, and preprocessing must be supplied
when constructing `OpenCVExpressionProvider`.
