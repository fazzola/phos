# PHOS Milestone Roadmap

The roadmap separates **implemented in code** from **verified as a runnable milestone**. Existing code may be ahead of the currently verified milestone; do not delete it, but do not automatically expand it.

## M1 — Eyes are runnable on PHOS

**Current priority: verify on target hardware.**

Implementation already present:
- [x] UI-neutral `FaceState`
- [x] basic expressive eye rendering
- [x] neutral / happy / curious / surprised / sleepy states
- [x] smooth animation/interpolation path
- [x] blink behavior
- [x] bounded pupil movement
- [x] standalone eye demo
- [x] display render loop independent from Vision inference

Verification still required:
- [ ] run eye demo on Raspberry Pi 3
- [ ] verify actual 800x600 display/fullscreen behavior
- [ ] verify smoothness and CPU usage are acceptable
- [ ] verify clean startup/shutdown on target hardware

**Done means:** PHOS can be started on the Pi and visibly demonstrate the eye states, smooth transitions, blink and pupil motion without Vision or AI.

## M2 — PHOS looks at a face

Existing foundation:
- [x] camera abstraction
- [x] Picamera2 adapter present
- [x] face detector abstraction/implementation present
- [x] publish provider-neutral normalized face position
- [x] map position through BehaviorEngine/FaceState with bounded smoothing

Milestone work/verification:
- [ ] confirm Pi Camera works on target hardware
- [ ] verify subtle bounded/smoothed pupil tracking
- [ ] verify face loss returns PHOS to idle behavior

Do not require expression classification to complete this milestone.

## M3 — PHOS reacts to facial expressions

Existing foundation:
- [x] expression provider abstraction
- [x] OpenCV DNN/ONNX provider implementation present
- [x] temporal smoothing present
- [x] stable-expression and face-lost event integration present
- [x] BehaviorEngine has initial reactions for selected expression labels

Remaining:
- [ ] select/test a lightweight ONNX expression model suitable for Raspberry Pi 3
- [ ] validate labels/input/preprocessing against the selected model
- [ ] benchmark detection/inference rate on target hardware
- [ ] verify stable happy/surprised/neutral reactions visually
- [ ] ensure negative observations do not mechanically make PHOS angry/sad
- [ ] verify no image/face persistence by default

## M4 — PHOS speaks and listens

AI foundation already present:
- [x] provider-neutral `LLMProvider` contract
- [x] provider adapter structure
- [x] provider-independent `RobotAgent` skeleton

Voice milestone:
- [ ] microphone abstraction/capture
- [ ] VAD or equivalent turn detection as needed
- [ ] speech-to-text
- [ ] validate at least one usable LLM provider end to end
- [ ] implement/validate `TTSProvider`
- [ ] benchmark Piper with an Italian voice on Raspberry Pi 3
- [ ] speaker/audio playback subsystem
- [ ] integrate RobotState transitions through listening/thinking/speaking
- [ ] verify the full microphone -> STT -> LLM -> TTS -> playback loop

## M5 — Home Assistant and physical integrations

- [ ] Home Assistant integration/tool layer
- [ ] explicit allowlists/policy for sensitive actions
- [ ] optional WebSocket event/state integration
- [ ] optional MQTT entities for PHOS status
- [ ] LEDs
- [ ] servos/motors
- [ ] additional sensors
- [ ] safety limits for actuators

## Rule
Each milestone must be runnable and verified on its own before the next major component is deliberately expanded.
