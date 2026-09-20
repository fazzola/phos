# PHOS Current State

This file is an implementation handoff for coding agents. It records what is present in the checked-out repository and distinguishes implementation from hardware verification.

## Identity and baseline
- Project: PHOS.
- Python namespace: `robot`.
- Target: Raspberry Pi 3.
- Display target: 5-inch 800x600.
- Microphone available; exact interface remains TBD.
- Raspberry Pi Camera is the intended Vision source; exact hardware availability/model must be confirmed in `docs/hardware.md`.

## Present in the repository

### Core and behavior
- Event bus and explicit `RobotState` state machine.
- `BehaviorEngine` under `src/robot/core/behavior_engine.py`.
- Behavior produces `FaceState` and handles blink/idle gaze.
- Robot states include IDLE, LISTENING, THINKING, SPEAKING, SLEEPING and ERROR.

### UI / eyes
- UI-neutral `FaceState` and expression/blink enums.
- Eye renderer/display runtime with smooth frame updates.
- Standalone eye demo under `src/robot/ui/demo.py`.
- Current README documents an 800x600/fullscreen runtime path and keyboard-driven eye demo.

### Vision
- Provider-neutral camera, face-detector and expression-provider contracts.
- Picamera2 camera adapter and OpenCV face detection/expression implementation are present.
- `VisionPipeline` rate-limits detection and expression inference independently and publishes stable-expression / face-lost events.
- Temporal expression smoothing is present. `BehaviorEngine` maps only stable
  observations to subtle `FaceState` reactions, refreshes sustained reactions,
  and decays them to baseline. UNKNOWN is explicit; negative classes never
  select a PHOS expression. Surprise is temporary with rearming/cooldown.
  Neutral perception defaults to disabled pending calibration; `RobotState`
  takes priority. Semantic thresholds and diagnostics are in `docs/vision.md`.
- `FaceState` includes a provider-neutral `VisualAccent`; the eye renderer
  smoothly applies its semantic neutral/warm/curious/alert/sleepy/error colors
  to eye and pupil appearance without depending on Vision labels.
- OpenCV Zoo MobileFaceNet is the selected expression replacement candidate;
  FER+ remains the rollback/comparison baseline. The existing provider supports
  both, with presets and inference timing. An in-memory paired camera benchmark
  is available as `python -m robot.vision.benchmark`. Pi CPU inference is
  measured; two camera comparisons had poor face detection coverage and
  showed no recognition improvement. A rotation probe did not resolve detection; see `docs/vision-model-evaluation.md` for
  model details, evidence, channel-order inconsistency and acceptance steps.
- Face-position tracking is implemented: Vision initially acquires the largest
  valid face, then prefers geometric continuity and publishes normalized selected-face
  position events, and `BehaviorEngine` smoothly maps them into bounded
  `FaceState` pupil targets. Hardware verification on the Pi Camera/display is
  still required.
- Expression crops are bounded squares with configurable margin and smoothed
  scale; two matching detections are required before inference. Debug logs expose
  all detections, selections and rejections. See `docs/vision.md` for geometric
  gates, reacquisition rules and physical crop verification.

### AI
- Provider-neutral `LLMProvider` contract and `RobotAgent` skeleton exist.
- OpenAI, Anthropic and local/LAN provider adapter modules exist.
- Provider maturity should be judged from code/tests rather than filename presence alone.

### Runtime
- An application runtime/coordinator already exists and can supervise Core/UI and optional Vision.
- This code predates the newer vertical-milestone discipline. Preserve it, but do not use its existence as a reason to expand unfinished subsystems automatically.

### Voice / TTS
- Voice package exists, but the complete microphone -> STT -> LLM -> TTS -> playback vertical slice is not yet implemented.
- TTS architecture remains provider-neutral with Piper as the preferred first local engine to benchmark when that milestone begins.

## Current development priority

The expression-reaction implementation needs target-hardware verification with
a selected lightweight ONNX model. Confirm the model's labels, dimensions and
preprocessing, then verify semantic happy/surprised confirmation and UNKNOWN
abstention on the Pi Camera/display while checking CPU use and clean shutdown.
Neither current model has demonstrated reliable recognition; neutral activation
requires calibration, not just a high softmax score.

## Known verification note

At the time this governance merge was prepared, the repository test suite had 30 tests, with 28 passing and 2 Vision tests failing only on exact floating-point equality around an averaged confidence value (`0.8` vs floating-point representations such as `0.8000000000000002`). This is an existing code/test issue, not introduced by governance files. Re-run the suite in the actual working checkout before relying on this note.

## Selectable expression providers

Local ONNX remains the default; optional AWS Rekognition is implemented behind
ExpressionProvider, with local tracking/cropping, bounded background requests,
cache expiry, change gating, stability gating and failure backoff. JSON settings
feed RuntimeConfig and can be overridden by CLI. Cloud cached samples retain
capture timestamps and do not advance semantic confirmation. See Vision and
installation for policy, privacy, exact commands and external credentials.
Mocked tests cover cloud behavior without credentials/network/cost. Physical
Pi/AWS validation, expression accuracy and cloud threshold calibration remain
outstanding. No web UI, automatic fallback or additional milestone is implemented.
