# PHOS Current State

This file is an implementation handoff for coding agents. It records what is present in the checked-out repository and distinguishes implementation from hardware verification.

## Identity and baseline
- Project: PHOS.
- Python namespace: `robot`.
- Target: Raspberry Pi 3.
- Display target: 5-inch 800x600.
- Microphone available; exact interface remains TBD.
- Display/eyes and Pi Camera/tracking are documented as operational in `docs/hardware.md`; exact camera model remains unspecified.

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
  `FaceState` pupil targets. Hardware operation is recorded in `docs/hardware.md`;
  fresh release regression remains required.
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

## Selectable expression providers

Local ONNX remains the default; optional AWS Rekognition is implemented behind
ExpressionProvider, with local tracking/cropping, bounded background requests,
cache expiry, change gating, stability gating and failure backoff. JSON settings
now come from the complete canonical `config/phos.json` and can be overridden
by deprecated CLI settings. Cloud cached samples retain
capture timestamps and do not advance semantic confirmation. See Vision and
installation for policy, privacy, exact commands and external credentials.
Mocked tests cover cloud behavior without credentials/network/cost. Physical
Pi/AWS validation, expression accuracy and cloud threshold calibration remain
outstanding. No automatic provider fallback is implemented.

## Canonical configuration

`robot.config` owns RuntimeConfig/CloudExpressionConfig, strict full-file schema
validation, config-relative paths and reusable atomic save. Runtime composition
passes JSON values for display, behavior, detector, Vision, expression smoothing,
local/AWS providers and logging. The default file enables only eyes. The old
expression-specific partial JSON files are removed; migrate existing deployments
using `docs/development.md`. No secrets are part of the model. `run_pi.sh` seeds
configuration without overwriting existing Pi settings. The optional web interface
reuses this model; see below. Startup flags remain deprecated
overrides pending a separately announced removal after consumers migrate.

## Web administration

Implemented: optional Flask/Waitress process, required canonical `web` section,
responsive domain pages with shared navigation, per-page merges through full
configuration validation/atomic saves, provider
selection, bootstrap password rotation, hashed local credentials, expiring
revocable sessions, CSRF and global password attempt throttling. Startup owns
worker cleanup and exposes the startup snapshot on a separate read-only Status
page. General provides navigation; Network, Display & Appearance, Vision,
Expression Recognition, Logging and Web Administration / Security expose only
implemented fields. Password management stays separate.
No live reload, AWS credential probe, automatic backup or Internet deployment.
See [user manual](web-administration.md) for installation and recovery. Tests are
hardware-free; Pi resource usage and LAN browser verification remain required.

## PHOS 1.0.0 finalization

The current implemented scope is frozen; see [release record](release-1.0.0.md)
and [deferred roadmap](roadmap.md). Version is authoritative in
`src/robot/__init__.py`, with package metadata, startup logs and Status using it.
Camera failure/partial-start and cancellation cleanup are hardened. Source sync
ships metadata, docs and the pinned web dependency snapshot while preserving
deployed settings/credentials. Packaged installs include the canonical JSON.

Release verification in this audit (Python 3.11.6):
- Relevant lifecycle/core/UI/configuration tests: 103 passed.
- Release metadata/packaged-config tests: 2 passed.
- Full suite: **242 passed, 1 skipped** in 123.66 seconds. The skipped OpenCV
  preprocessing test at `tests/vision/test_expression.py:105` requires `cv2`,
  unavailable in this environment. Optional dependency installation was declined.
- Real loopback web-worker startup/shutdown passed within the full suite;
  authentication/domain tests made no real AWS calls.
- Source distribution built with version 1.0.0; canonical JSON, web assets,
  manuals, dependency snapshot and tests verified in the archive.
- Pinned web versions match the installed environment; `pip check`, Python
  compilation, `sh -n run_pi.sh`, startup `--help` and `git diff --check` passed.
- Fresh wheel installation was not run (wheel/build tools unavailable); the
  source deployment path, sdist contents and installed-config lookup were checked.
Physical Pi regression and AWS service verification were not performed during
this source audit. Expression quality remains unproven as documented above.
