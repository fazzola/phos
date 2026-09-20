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

### Visual reaction semantics

Vision classifies an uncertain **visible facial expression**, not a person's
internal emotional state. `BehaviorEngine` gives PHOS its own response and
produces the UI-neutral `FaceState`; Vision never selects renderer geometry or
colors directly.

| Stable visible-expression observation | PHOS behavior | `FaceExpression` | `VisualAccent` |
| --- | --- | --- | --- |
| neutral | calm acknowledgement | neutral | neutral |
| happiness / happy | warm, friendly response | happy | warm |
| surprise / surprised | alert, open response | surprised | alert |
| unknown (including rejected/negative FER classes) | preserve and decay to baseline | unchanged, then neutral | unchanged, then neutral |

Vision publishes semantic evidence, not individual negative FER labels.
UNKNOWN is an explicit absence of accepted evidence. It is distinct from a
positively confirmed neutral observation; current uncalibrated models abstain
on neutral. See `docs/vision.md` for thresholds and temporal rules.

`FaceState` carries the expression, semantic `VisualAccent`, and
`reaction_strength` independently. The renderer maps accents to its own color
palette: neutral light cyan/white, warm turquoise, curious cyan/blue, alert
amber, sleepy muted violet, and error red. Strength blends the neutral and
accent colors, as well as the existing eye-shape profile. Eye, pupil, and
background color transitions interpolate at render cadence rather than jumping
at Vision inference cadence.

Robot state remains higher priority than Vision: listening/thinking use a
curious accent, speaking uses warm, sleeping uses sleepy, and error uses red.
Happy reactions refresh only from confirmed observations and decay smoothly
back to neutral when evidence stops. Surprise is temporary, cannot refresh from
a sustained pose, and needs confirmed alternative evidence plus a cooldown
to rearm. UNKNOWN allows normal decay. Face tracking and blink timing
remain independent from expression inference.

`VisualAccent` is deliberately provider-neutral. A future WS2812B LED-ring
adapter may consume the same semantic state, but no LED integration or hardware
control belongs in the current display/Vision path.

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

### Local/cloud expression boundary

Camera -> local detector/selector/square crop -> `ExpressionProvider`
(`OpenCVExpressionProvider` or optional `AWSExpressionProvider`) -> existing
`ExpressionSmoother` semantics -> Vision events -> `BehaviorEngine` -> `FaceState`.
AWS SDK objects remain in its adapter. Cloud requests use a single background
asyncio task plus `to_thread`, independent of capture/tracking/render cadence.
Provider lifecycle invalidation discards evidence across tracking discontinuity.
Cached `ExpressionObservation.sampled_at` preserves provenance so reads cannot
manufacture temporal confirmation. Local observations retain their existing
cadence and semantics. See [Vision](vision.md#selectable-local--aws-expressions).

`config/phos.json` is the canonical source of normal runtime settings. The
provider-neutral `robot.config` module validates its required sections and maps
them to `RuntimeConfig` and `CloudExpressionConfig`, with no hardware, SDK or
argparse dependencies. The runtime passes only relevant typed values to each
subsystem. Startup validates before constructing any camera/display components;
paths are relative to the configuration file. Existing constructor fallback
values are not consulted by application composition.

The same file/dict validation, serialization and atomic persistence must be used
by the optional web configuration interface. Credentials stay in the external AWS
SDK chain and are never fields in application settings. New ordinary settings
must extend this central model/file, not standalone CLI arguments. Existing CLI
settings are deprecated explicit overrides during migration. There is no live reload. See [configuration reference](development.md#configuration).

## Administration adapter

`robot.web` wraps the canonical configuration service with a server-rendered
Flask editor. Waitress runs in a separate process owned by the main startup
lifecycle, independent of rendering/Vision. The worker receives the startup
settings for a saved-versus-startup comparison, not live status monitoring.
Its password-storage service is separate from runtime JSON; Flask sessions and
Flask-WTF protect administration actions. Core, providers and the renderer have
no web-framework dependency. See the [web manual](web-administration.md).

Administration domains select canonical field paths for presentation only. Each
page merges its submitted fields into the complete document and calls the same
validation/persistence boundary. System / Status is read-only; password changes
use the separate credential service. See the manual for the domain-to-field map.
