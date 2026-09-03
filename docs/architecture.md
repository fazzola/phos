# PHOS Architecture

## High-level model

```text
                +----------------------+
                |      Robot Core      |
                | lifecycle/state/events|
                +----------+-----------+
                           |
          +----------------+----------------+
          |                |                |
      +---v---+        +---v---+        +---v---+
      | Voice |        |  AI   |        |  UI   |
      +---+---+        +---+---+        +---+---+
          |                |                |
      microphone       agent/tools      display/eyes
          |                |
      STT / TTS        LLMProvider
                           |
                    provider adapters

Vision is an independent subsystem that publishes provider-neutral observations/events to Core.
Hardware-specific access remains behind adapters/interfaces.
```

## Core principles

### 1. Separation of concerns
Core coordinates lifecycle, state, events and behavior. Subsystems implement capabilities.

### 2. Hardware abstraction
Business logic depends on interfaces, not GPIO/device-specific code. Ordinary unit tests must not require physical hardware.

### 3. Events where they reduce coupling
Use events for meaningful asynchronous state changes such as speech recognition, robot-state changes or stable Vision observations. Do not create an event merely to avoid a normal function call.

### 4. Explicit robot state
The existing state model includes `IDLE`, `LISTENING`, `THINKING`, `SPEAKING`, `SLEEPING` and `ERROR`. Keep transitions explicit and testable.

### 5. Incremental verification
PHOS is developed through runnable vertical milestones. Existing code may be ahead of the current verified milestone, but new work should prove one capability before expanding the next major subsystem.

## Visual / behavior path

```text
Camera
  -> Vision
  -> stable observations/events
  -> Robot Core
  -> BehaviorEngine
  -> FaceState
  -> EyeRenderer
  -> EyeDisplay
```

Vision observes. Behavior interprets observations in the context of PHOS's own `RobotState`. `EyeRenderer` consumes only `FaceState` and handles rendering/animation details.

The face-rendering frequency is independent from Vision timing so the display can remain smooth while detection/inference runs at a lower rate.

`BehaviorEngine` currently lives under `src/robot/core/`, because behavior is part of Core orchestration in the checked-out implementation.

## Runtime

`PhosRuntime` is the current application coordinator. It supervises Core/UI and optional Vision tasks and handles lifecycle/failure boundaries.

Keep orchestration thin. Do not move expression classification, rendering geometry or model-provider logic into the runtime. Camera/inference/render/audio work must not collapse into a single blocking loop.

The existence of the integrated runtime does not override milestone discipline: each capability still needs independent runnable verification.

## AI provider architecture

```text
RobotAgent / behaviors / tools
          |
          v
     LLMProvider
          |
   +------+------+-------------+
   |             |             |
OpenAI       Anthropic      Local/LAN
 adapter       adapter       adapter
```

`LLMProvider` is the only model interface visible to the rest of the robot. Provider adapters translate neutral messages/tools/tool calls to and from vendor-specific formats.

The primary conversational model is not assumed to run on Raspberry Pi 3. Cloud API or LAN-hosted models are valid; a deliberately small local fallback may be explored later.

## Voice architecture

Preferred vertical path:

```text
microphone -> STT -> RobotAgent/LLMProvider -> TTSProvider -> playback -> speaker
```

TTS synthesis and playback/device management are separate responsibilities. Piper is the preferred first local TTS candidate to benchmark on Raspberry Pi 3, not a hard-coded dependency of callers.

## Vision architecture

```text
Picamera2CameraProvider
        -> FaceDetector
        -> ExpressionProvider
        -> ExpressionSmoother
        -> provider-neutral Vision result/event
```

Use lightweight processing appropriate for Raspberry Pi 3. Expression classification describes uncertain visible facial-expression patterns, not a person's true mental/emotional state. No identity recognition or frame persistence by default.

## Home Assistant relationship

Home Assistant is an integration/tool surface, not PHOS's brain. Commands may use REST, state/events may use WebSocket, and MQTT may later expose PHOS entities. AI access must be mediated by explicit tools/services and allowlists; sensitive actions require explicit policy.
