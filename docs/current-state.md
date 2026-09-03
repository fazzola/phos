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
- Temporal expression smoothing is present.
- A concrete lightweight ONNX expression model is not selected/bundled; model path/labels/preprocessing remain configuration concerns.
- Face-position tracking is implemented: Vision publishes normalized largest-face
  position events, and `BehaviorEngine` smoothly maps them into bounded
  `FaceState` pupil targets. Hardware verification on the Pi Camera/display is
  still required.

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

The current priority is to verify the completed face-tracking implementation
on target hardware:
1. run `python3 src/robot/main.py --face-tracking` with the Pi Camera;
2. verify the pupils follow the largest visible face smoothly and remain bounded;
3. verify face loss returns PHOS to idle gaze;
4. verify startup/shutdown and CPU use on the Raspberry Pi 3 and real 800x600 display;
5. record camera/display/backend issues before proceeding.

Do not enable or expand expression reactions while verifying this face-tracking
milestone. Existing expression/runtime code remains separate.

## Known verification note

At the time this governance merge was prepared, the repository test suite had 30 tests, with 28 passing and 2 Vision tests failing only on exact floating-point equality around an averaged confidence value (`0.8` vs floating-point representations such as `0.8000000000000002`). This is an existing code/test issue, not introduced by governance files. Re-run the suite in the actual working checkout before relying on this note.
