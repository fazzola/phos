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
- Face-position tracking into gaze is not yet the documented verified milestone: current Vision events focus on stable expression and face loss.

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

The next priority is **not adding more subsystems**. Verify the existing eye milestone concretely:
1. run the standalone eye demo;
2. verify neutral/happy/curious/surprised/sleepy visual states;
3. verify blink, smooth transitions and bounded pupil motion;
4. verify startup/shutdown on the Raspberry Pi 3 and real 800x600 display;
5. record any display/backend issues before proceeding.

After M1 is verified, move to face-position tracking (M2). Existing expression/runtime code may remain in place but should not be expanded until the preceding runnable milestone is stable.

## Known verification note

At the time this governance merge was prepared, the repository test suite had 30 tests, with 28 passing and 2 Vision tests failing only on exact floating-point equality around an averaged confidence value (`0.8` vs floating-point representations such as `0.8000000000000002`). This is an existing code/test issue, not introduced by governance files. Re-run the suite in the actual working checkout before relying on this note.
