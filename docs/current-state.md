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

Complete the remaining 1.0.0 release acceptance checks; do not expand scope.
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
worker cleanup and exposes parent-owned active configuration metadata on a
separate read-only Status page. General provides navigation; Network, Display & Appearance, Vision,
Expression Recognition, Logging and Web Administration / Security expose only
implemented fields. Password management stays separate.
Logging level, iris appearance and camera-preview settings are live-reloadable after full canonical validation. Confirmed
PHOS restart uses the supplied user systemd service; manual launches reject
browser restart. No OS reboot, AWS credential probe, automatic backup or Internet
deployment.
See [user manual](web-administration.md) for installation and recovery. Tests are
hardware-free; Pi resource usage and LAN browser verification remain required.

## PHOS 1.0.0 finalization

The current implemented scope is frozen; see [release record](release-1.0.0.md)
and [deferred roadmap](roadmap.md). Version is authoritative in
`src/robot/__init__.py`, with package metadata, startup logs and Status using it.
Camera failure/partial-start and cancellation cleanup are hardened. Source sync
ships metadata, docs and the pinned web dependency snapshot while preserving
deployed settings/credentials. Packaged installs include the canonical JSON.

## Validated reload and managed restart

`robot.lifecycle.LifecycleService` owns the active snapshot, load timestamp and
fixed status/reload/restart policy. The web worker uses a local process channel;
it cannot submit commands or paths. Reload validates the entire saved file and
applies logging level, iris appearance and camera preview through their application-service
boundaries, preserving AWS SDK log suppression. Other changed fields are listed
as restart-required. Authenticated restart requires CSRF and
one-use explicit confirmation, then graceful runtime shutdown and exit 75.
`deploy/phos.service` performs process replacement under the desktop user with
no sudo/polkit or shell endpoint. Source sync includes the unit but never enables
it. System actions remain separate from ordinary config forms. OS reboot and all
previously deferred roadmap capabilities remain deferred.

## Eye appearance refinement

Display & Appearance now validates and exposes `display.iris_color` in the
canonical JSON. EyeRenderer receives this theme at startup and layers lightweight
Canvas eye-body, iris, pupil and highlight geometry. FaceState continues to
supply semantic reaction intent; expression labels/providers do not control
rendering. Theme changes apply after configuration reload without restarting
Vision or other runtime services. Raspberry Pi frame-rate impact awaits
target hardware verification.


## Local camera picture-in-picture

An optional diagnostic preview is disabled by default. When active it uses the
existing Vision camera owner, retains only a latest-frame reference in memory,
and passes a UI-neutral image/diagnostic value through PhosRuntime to the display
compositor. Web Admin → Vision settings apply through validated configuration
reload. Frames are neither persisted nor exposed through Web Admin. Enabling the
preview starts the dormant pipeline if no other Vision feature is running;
disabling it releases the camera when no other Vision feature needs it.

## Live eye appearance reload verification

Only `display.iris_color` is currently a configurable eye-style setting and is
live-reloadable. Semantic accents remain BehaviorEngine-produced FaceState and
need no configuration reload. The lifecycle service validates the whole
canonical document, then gives the typed RuntimeConfig to PhosRuntime. Its
display-loop boundary safely queues the iris theme onto the asyncio render
thread; EyeRenderer interpolates the color on subsequent frames. Reload does not
rebuild Core, Vision, camera, BehaviorEngine, providers or the renderer object.
Mixed changes apply logging, iris appearance and preview while retaining other changed
fields in `restart_required`. Invalid configuration applies nothing.

## Final release hardening

The source version remains exactly **1.0.0**. Release status is **not ready to tag**
until the remaining [release checklist](release-1.0.0.md#release-checklist) gates
are verified. Earlier test counts are superseded by this audit; git history retains
those historical records.

Implemented fixes: preview defaults off; reload waits for camera lifecycle
acceptance and preserves configuration-relative paths; failed/cancelled startup
releases resources; shutdown drains reload tasks and Vision supervisor waiters;
intentional preview-only camera stop does not trigger a subsystem failure; stopped
pipelines clear snapshots; rapid toggling cannot build up encoder jobs; preview converts BGR to RGB for Tk
without altering Vision/model preprocessing. Runtime
and web-worker failures propagate a nonzero exit so systemd can recover.
Invalid configuration applies nothing. A later hardware apply failure leaves
previously successful appearance changes recorded and reports the failure.

Verification (macOS, Python 3.11.6):

- Focused runtime/main/lifecycle/configuration/AWS-mock/worker-cleanup checks:
  **129 passed**.
- Full suite rechecked on 2026-09-23: **285 passed, 1 skipped, 2 failed** in 219.08 seconds
  (`.venv/bin/python -m pytest -q --tb=short -rs`). Both failures are sandbox
  `PermissionError` binding localhost in `test_real_web_worker_serves_and_releases_port`
  and `test_real_worker_reload_reaches_parent_application`; permission for an
  unsandboxed rerun was declined. The skip is `tests/vision/test_expression.py:105`
  because `cv2` is unavailable. No test was weakened/skipped to hide these failures.
  Installing OpenCV and wheel and rerunning the localhost tests outside the
  sandbox were requested again during this verification and declined. These
  acceptance checks remain blocked; no additional implementation change was needed.
- Final acknowledgement-path runtime/main/lifecycle/UI checks: **58 passed**
  after retaining completion acknowledgement across an IPC timeout.
- No real AWS calls or Pi/display/systemd operations were performed. Mobile/tablet
  review covered responsive CSS/templates and form tests, not a physical browser.
- `pip check`, canonical version/config validation, CLI help, shell syntax and
  diff whitespace checks pass. Source archive built with 1.0.0 metadata and
  required canonical config, unit, web assets and dependency snapshot verified.
- Wheel/editable installation unavailable locally (`bdist_wheel` missing).
  The local venv has an old installed 0.1.0 package; source launch and tests select
  `src` explicitly. This is not the authoritative release version.
- Targeted tracked-file scans found no AWS key/private-key patterns or tracked
  generated artifacts. Functional deprecated CLI overrides, eye demo and paired
  Vision benchmark are retained; no roadmap scaffolding was removed.

The fresh-install guide now provides one complete path through dependencies,
configuration, model/SDK selection, credentials and the recommended user service.
Release documentation owns exact acceptance steps and performance limitations;
no new Pi performance or recognition-quality claim is made.
