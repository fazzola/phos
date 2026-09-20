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
        +--> normalized face position --> Robot Core --> BehaviorEngine --> FaceState
        |
        +--> ExpressionProvider --> temporal smoothing --> Robot Core
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

## Face continuity and expression crops

The detector previously sorted boxes by area and the pipeline selected the
largest independently on every frame. That allowed a larger false positive or
second face to replace the previous target immediately; rectangular crops also
changed aspect ratio before model resize. These code paths explain a mechanism
for instability, but bounding-box logs alone cannot establish that a detection
is actually a face. The historical camera tests did not visually verify crops.

`FaceSelector`, an internal geometric helper in Vision, now associates detections
with the last selected box. It does not recognize identity or store images.

- Initial acquisition chooses the largest valid detection, with deterministic
  position tie-breaking. Invalid/out-of-frame boxes and aspect ratios outside
  0.5–2.0 are rejected. Haar settings and model preprocessing remain unchanged.
- Continuations require width and height ratios between 2/3 and 1.5, center
  displacement no greater than 0.60 times the previous longest side, and either
  IoU of at least 0.15 or displacement no greater than 0.25 sides. Compatible
  candidates rank by `2 * IoU - normalized_distance - absolute_log_size_changes`,
  rather than area. Other boxes are logged as competing detections or rejected
  position/size jumps. These are conservative geometric heuristics, not proof
  of a real face or person identity.
- The last match is remembered for at most one second. Missing/rejected boxes
  do not advance that timeout. During a miss, no stale box reaches inference
  or gaze; existing face-lost behavior runs and expression evidence resets.
  After expiry a new acquisition is allowed, without mixing expression evidence
  across tracks. Frame-size changes also reset continuity.
- Gaze immediately receives the selected **current detection's** normalized
  center through the existing event. Expression inference waits for two
  consecutive matching detection cycles, including after a miss. This rejects
  one-frame expression crops while retaining responsive face tracking.
- Crop side length uses the longest detected side with an EMA coefficient of
  0.5 to reduce scale jitter. The center follows the current detection, avoiding
  added gaze/crop motion lag. The square always contains the current detected
  face, even when smoothing would otherwise make it too small.
- Default margin is 10% per side: a stationary 100-pixel face yields a 120-pixel
  square. Set `--expression-crop-margin 0.10` (valid range 0–0.5) or
  `RuntimeConfig.expression_crop_margin` to configure it. Near image edges the
  square shifts inside the frame; margin is reduced if necessary. If no square
  can contain the detected face within the image, expression inference is
  skipped. There is no padding, non-square stretching, or saved image.

Add `--expression-debug` to the existing launch command to log every detection
cycle's full box list, selected box, selection reason, rejected boxes/reasons,
and expression eligibility. Expression passes also log the final crop rectangle,
margin and smoothed size. With tracking alone, use
`python3 src/robot/main.py --face-tracking --expression-debug` to isolate detection
without running FER. Disable diagnostics after testing to limit log volume.
The paired benchmark uses the same selector and default square crop policy,
and records detected/selected/rejected boxes and selection reasons numerically.
Historical benchmark results used independent largest-box selection and tight
rectangular crops, so they are not directly comparable preprocessing baselines.

### Physical crop verification on Raspberry Pi

1. Start with the empty scene, then enter and hold still for 20–30 seconds.
   Persistent selected boxes while nobody is present indicate false positives;
   the new continuity rules cannot reject a consistently detected background
   pattern merely because it is stable. Confirm the real face is in view using
   the camera preview separately if needed; stop PHOS before another process
   acquires the camera. No preview/image storage is added to the runtime.
2. Move slowly left/right and nearer/farther. Look for `continuity_match`, modest
   crop-size changes, correct gaze, and consistently square crop coordinates.
   Inspect whether boxes cover the actual face; numeric stability is insufficient
   evidence of correct framing. Repeated `size_jump`/`position_jump` during normal
   movement may mean these initial gates need Pi-side tuning.
3. Introduce a second person, including a larger face away from the current
   target. PHOS should retain the first plausible track. Crossing/overlapping
   people remain ambiguous without identity recognition.
4. Leave/re-enter, move abruptly, or briefly occlude the face. Rejected detections
   must not reach FER; gaze uses existing face-loss behavior. Reacquisition after
   the one-second timeout requires a second matching detection before inference.
5. Approach each image edge. Verify crop coordinates stay within 640x480 and the
   detected face remains contained. Then repeat neutral/smile/surprise at a fixed
   distance and lighting while comparing FER outputs. Do not infer model accuracy
   until framing is verified. Check display smoothness, CPU load and shutdown.

This change does not tune FERPlus semantic thresholds or BehaviorEngine reactions.
No fresh physical camera evidence has been collected for these selection defaults.

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

The replacement candidate is OpenCV Zoo MobileFaceNet FP32 ONNX; see
[model evaluation](vision-model-evaluation.md) for its contract, limitations,
measurements and paired camera test. It runs through the existing provider and
runtime configuration. Production promotion awaits Pi camera verification.

The previous baseline is ONNX Model Zoo `emotion-ferplus-8.onnx`. Its output labels must stay
in this exact order: `neutral`, `happiness`, `surprise`, `sadness`, `anger`,
`disgust`, `fear`, `contempt`.

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

## Semantic evidence and temporal confirmation

`ExpressionProvider` retains its model-specific top label/confidence and now
also supplies the complete labelled probability distribution. `ExpressionSmoother`
interprets that distribution before accumulating temporal evidence. Only four
semantic labels leave this path: `neutral`, `happy` (smile/happy-like),
`surprised` (surprise-like), and `unknown`. These are visible appearance cues,
not measurements of internal emotion or direct measurements of eyelid opening.

Conservative initial defaults (not calibrated accuracy guarantees):

| Semantic candidate | Minimum probability | Margin over next raw class | Consecutive samples | Minimum duration |
| --- | --- | --- | --- | --- |
| happy / happiness | 0.80 | 0.30 | 3 | 800 ms |
| surprise / surprised | 0.85 | 0.35 | 3 | 600 ms |
| neutral, only when explicitly enabled after calibration | 0.95 | 0.50 | 3 | 1200 ms |

The existing `minimum_confidence` constructor setting is an additional floor;
it cannot lower these class thresholds. The class floors already imply strong
margins for normalized distributions; the margin check makes the ambiguity rule
explicit. Evidence must remain consecutive and gaps must not exceed 1.5 seconds.
A changed candidate, rejected/missing prediction, no face, duplicate/backward
timestamp or excessive gap resets confirmation. Count alone cannot confirm a
burst of fast samples. Storage is bounded to the confirmation count, with recent
confidence averaged; duration records the current uninterrupted run.

**UNKNOWN is abstention, never a neutral vote.** Missing distributions (including
legacy top-label-only providers), malformed probabilities, negative/unsupported
classes, weak evidence and pending confirmation produce UNKNOWN. No negative
FER class maps to a PHOS expression. A missing face still uses the existing
face-lost event and clears evidence. Face tracking remains independent.

Neutral is **disabled by default**, including in the runtime and benchmark.
The recorded Pi comparisons show false neutral even at high confidence, so
raising a threshold alone is insufficient justification for accepting it.
`ExpressionSmoother(neutral_enabled=True)` is available for a subsequently
validated model/camera configuration; it still requires positive neutral
probability, margin and temporal evidence. There is deliberately no automatic
fallback from rejected smile/surprise to neutral.

The existing `vision.visual_expression_stable` event carries confirmed useful
observations **or explicit UNKNOWN**, preserving its name and payload fields.
For UNKNOWN, `confidence=0` means no accepted semantic evidence, not a model
probability, and `observed_for_ms=0`. `VisionResult` carries the same expression;
its status is UNSTABLE during confirmation, UNKNOWN on rejection, and STABLE
on acceptance. NOT_DUE/no-face remain separate outcomes.

UNKNOWN does not refresh or replace a BehaviorEngine reaction. PHOS preserves
its current face momentarily while the existing decay returns it to baseline
(at 0.30 strength/second, at most three seconds from strength 0.90). That baseline
NEUTRAL face is **not** a claim that the observed person looks neutral.
Confirmed happy observations refresh the warm reaction. Surprise is a temporary
reaction: repeated surprise observations cannot refresh it. A confirmed happy
or neutral observation rearms surprise, with at least four seconds between
surprise triggers; UNKNOWN and face loss do not rearm it. RobotState retains
priority, and renderer interpolation and gaze remain unchanged.

With `--expression-debug`, each inference logs raw scores/probabilities, ranked
top classes, final semantic result, acceptance/rejection reason and temporal
candidate/count/duration/confirmation. Reasons include `neutral_not_calibrated`,
`below_class_threshold`, `unsupported_class`, `missing_distribution`,
`invalid_distribution`, `temporal_pending`, and `confirmed`. Images are not saved.
The paired benchmark uses this same policy and includes distributions, reasons,
temporal state, UNKNOWN fraction and raw-neutral fraction alongside accepted
semantic statistics. Old benchmark measurements predate this policy.

## Model usefulness and geometric cues

The [recorded paired camera evaluation](vision-model-evaluation.md) demonstrated
neither reliable smile/surprise discrimination nor reliable neutral detection.
Both models repeatedly selected neutral for prompted non-neutral poses; poor
face coverage and unverified crops prevent assigning model-level accuracy.
FER remains useful as an experimental source of probability evidence and timing
measurements. This policy contains its failures; it cannot recover a smile that
the model scores as neutral or prove that a confident smile score is correct.

Inspection of `OpenCVFaceDetector` and `FaceRegion` shows only a Haar bounding
rectangle and normalized center. No mouth corners, eyelid points, eye opening,
landmarks or calibrated neutral facial geometry are available. Rectangle size
and movement cannot establish a smile or surprise. Consequently no geometric
expression claim or new detector/framework is introduced. A future lightweight
cue adapter would need independently validated mouth/eyelid measurements and
Pi 3 end-to-end timing before fusion; a heavy landmark runtime is not justified
by the current evidence. Existing camera channel-order inconsistency remains a
separate documented limitation below; this change preserves that runtime.

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
captures RGB frames in memory and rate-limits Haar face detection. For every
detection interval with a face, it publishes `vision.face_position`, whose
`face_position.x` and `face_position.y` are the detected face center normalized
to `[-1, 1]` in camera coordinates. Vision does not choose pupil geometry;
`BehaviorEngine` clamps and smooths that provider-neutral attention input into
`FaceState`. When a face is lost, Vision publishes `vision.face_lost`.

Expression inference remains optional and independently rate-limited. When it
is configured, the pipeline publishes stable observations as
`vision.visual_expression_stable`; its payload contains
`visual_expression.label`, `confidence`, and `observed_for_ms` and does not
make a claim about internal emotional state.

`BehaviorEngine` is the only consumer that turns accepted semantic observations
into eye intent, following the evidence/UNKNOWN rules above. The provider-neutral
behavior and visual-accent contract lives in `docs/architecture.md`.

The default Pi adapter uses `Picamera2CameraProvider` at 640x480. Install the
Pi Camera and OpenCV dependencies using the Raspberry Pi OS instructions in
`docs/installation.md`, which includes the MobileFaceNet candidate launch command.
For rollback/comparison, the ONNX Model Zoo FER+ baseline expects a
`1x1x64x64` grayscale input and emits eight scores. The provider converts the
RGB face crop to grayscale before creating its OpenCV DNN blob. Start it with:

```bash
python3 src/robot/main.py \
  --expression-model models/expression/emotion-ferplus-8.onnx \
  --expression-labels neutral,happiness,surprise,sadness,anger,disgust,fear,contempt \
  --expression-input-size 64x64 \
  --expression-grayscale \
  --expression-scale 1 \
  --expression-mean 0,0,0 \
  --expression-no-swap-rb
```

FER+ preprocessing uses unscaled grayscale pixel values (`scale=1`), zero mean
and no channel swap. `happiness` and `surprise` are candidates for happy and surprised semantics;
`sadness`, `anger`, `disgust`, `fear`, and `contempt` produce UNKNOWN. These model-specific names never reach
the renderer.

For temporary Pi-side inspection without saving camera data, add
`--expression-debug` to that command. It logs the selected face rectangle and
crop shape, the grayscale/blob shapes, raw FER+ scores, softmax probabilities,
forward inference time, and whether the smoother rejected or published the observation. Remove the
flag after diagnosis because it logs every expression inference.
Face tracking alone needs no ONNX model: start it with
`python3 src/robot/main.py --face-tracking`.

### Camera channel-order inconsistency

The camera adapter currently requests Picamera2 `RGB888`, which yields BGR
array bytes despite the adapter's RGB documentation. The detector and legacy
FER+ grayscale conversion use `COLOR_RGB2GRAY`. The MobileFaceNet configuration
swaps channels to obtain the required RGB tensor. This evaluation preserves
the existing detector and FER+ baseline so results compare against current PHOS;
it does not silently change the camera contract. A future correction must update
camera, detector and expression configurations together and repeat the baseline.
See the [Picamera2 format mapping](https://github.com/raspberrypi/picamera2/blob/main/picamera2/request.py).
