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
  -> EyeRenderer -> EyeDisplay composition

Vision latest preview snapshot -> PhosRuntime -> EyeDisplay composition
```

Vision observes. Behavior interprets observations in the context of PHOS's own `RobotState`. `EyeRenderer` consumes only `FaceState` and handles rendering/animation details. The display adapter may compose an optional local diagnostic preview from a UI-neutral snapshot supplied by `PhosRuntime`; it never accesses camera or Vision providers.

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
settings are deprecated explicit overrides during migration. Logging level, display iris appearance and camera-preview settings can be reloaded through the lifecycle service; other subsystem changes require restart. See [configuration reference](development.md#configuration).

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

## Shared application services for control surfaces

Web, future remote API, MCP and Voice are adapters around PHOS application
services. They reuse the same validation, authorization, configuration and
behavior-command services; they must not reach into GPIO, hardware adapters,
provider objects, renderer state or other subsystem internals. Add an application
service when an approved capability needs one, rather than duplicating behavior
in each surface. The current configuration service is the implemented example;
remote-control/API/MCP/Voice services remain deferred after 1.0.0.


## Application lifecycle boundary

`robot.lifecycle.LifecycleService` owns the active-configuration snapshot and
allowed status/reload/restart operations. Reload validates the full canonical
file before applying logging level, iris appearance and camera preview through their
application-service boundaries. Other changes remain pending. The parent process serves a bounded local process channel to the web
worker; adapters cannot submit shell commands, paths or arbitrary configuration
payloads. Future API/MCP surfaces must use the same policy service.

The supplied user systemd service owns process replacement. A confirmed restart
requests graceful runtime shutdown and exit code 75; systemd restarts the same
entry point. The web adapter neither runs OS commands nor spawns replacements.
Runtime subsystem and web-worker failures propagate as nonzero process exits for
systemd recovery. Preview reload is acknowledged after camera start/stop acceptance;
failed starts release partially acquired camera resources, and shutdown drains
preview tasks and supervisor waiters. Manual launches reject browser restart. OS reboot and general remote control
remain out of scope. See installation for display-session environment and service
permissions. Status reflects configured values, not a new health-monitoring layer.


## Eye appearance

The Display & Appearance configuration supplies the validated named iris theme
to EyeRenderer at startup. EyeRenderer still consumes only FaceState and renderer
style configuration; expression/provider labels never reach the renderer.
Semantic visual accents continue to pass through BehaviorEngine and FaceState.
Tk draws layered eye-body, iris, pupil and highlight primitives without a
raster-processing pipeline. Iris appearance can be applied live through the
configuration lifecycle and render-loop queue; display geometry/backend changes
still require PHOS restart.


## Environmental sensor service

The separately approved BME280/BMP280 addition follows:

```text
BME280 / BMP280 -> selected hardware provider -> EnvironmentalSensorService
        -> PhosRuntime.sensor_status -> LifecycleService status snapshot
        -> existing local process channel -> authenticated Web Admin Sensors
```

`robot.sensors` owns the provider-neutral contract, immutable measurements and
latest-state service. The `robot.hardware` adapters alone know the SMBus/driver APIs.
`hardware.environmental.environmental_provider_type` centralizes selection and
capabilities. Both return `EnvironmentalReading` with temperature/pressure and
nullable `humidity_percent`; BMP280 must return null, BME280 must supply humidity.
The service validates that invariant using declared available measurements.
The runtime constructs and starts/stops the service without sensor decisions in
Core, BehaviorEngine, EyeRenderer or Vision. Future compatible environmental
providers reuse this boundary; other kinds of sensors need their own typed
measurements rather than forcing them into temperature/humidity/pressure fields.

One daemon worker serializes all provider calls; disabled means no worker,
provider construction, vendor imports or I2C open. It retries initialization after
failures, retains no history and exposes only finite valid current measurements.
Snapshot metadata includes active sensor type, available measurements, availability/status, UTC last success, monotonic age
and sanitized error type. Failed or stale snapshots contain no current values.
A blocked native call cannot stop the render loop or grow a work queue; stop
signals the worker and awaits at most one second. The owner closes the bus when
I/O returns; process exit releases it if stuck. No concurrent bus close is used.

All settings are restart-only under existing lifecycle classification. Save and
Reload do not restart any subsystem. Only an explicitly requested PHOS restart
reinitializes hardware. The Sensors page reads in-memory state via shared services,
never imports a driver or infers availability from saved enabled/address values.
The existing authenticated process channel carries the snapshot; no new API or
IPC operation is exposed. See ADR-022, [hardware](hardware.md#bme280) and
[configuration migration](development.md#environmental-configuration-migration).


### CCS811 air-quality extension

`hardware.CCS811Provider → AirQualitySensorService → PhosRuntime.sensor_status`
uses the same lifecycle status channel and authenticated Sensors page. An
immutable `AirQualityReading` holds eCO2 ppm / TVOC ppb; environmental measurement
interfaces remain unchanged. The two services reuse the existing worker algorithm
through a private base, with typed reading hooks. Each enabled sensor has one
worker and its adapter-owned smbus2 handle on bus 1. No rendering, Vision, web
handler or BehaviorEngine accesses these adapters.

Expected readiness/conditioning uses `SensorNotReady`, keeping the device open
and polling at the configured interval. Faults use the shared reconnect/backoff;
failed/stale readings are hidden and shutdown remains bounded per worker.
A stalled warm-up poll also becomes unavailable after its freshness timeout.
Disabled means no provider construction, imports or bus operations.

Environmental compensation flows through the environmental service's immutable,
fresh snapshot boundary to the air-quality service, then the provider. No driver
references another driver. The UI receives only state/metadata. Missing humidity
(including BMP280) or invalid/stale inputs restore device defaults; baseline
persistence and behavior integration remain deferred. See ADR-023 and the
[installation policy](installation.md#optional-ccs811-air-quality-sensor).

### MPU-6050 IMU extension

`hardware.MPU6050Provider → IMUSensorService → PhosRuntime.sensor_status` uses
the same worker, freshness, retry and authenticated status boundary as the other
sensors. `IMUReading` holds acceleration X/Y/Z in m/s² and angular velocity X/Y/Z
in °/s. The hardware adapter alone knows MPU-6050 registers and smbus2; Web Admin
only reads snapshots and edits canonical `sensors.imu` settings. No BehaviorEngine,
EyeRenderer or Vision component receives IMU readings. The adapter applies fixed
±2 g / ±250 °/s scale factors only; offset calibration, fusion and orientation are
outside this capability.

### Motion interpretation extension

`IMUReading → MotionInterpreter → MotionState / MotionEvent` is a pure,
provider-neutral layer between IMU state and future consumers. It never accesses
the MPU-6050, GPIO, Web handlers, Vision, EyeRenderer or BehaviorEngine. The IMU
worker supplies timestamped samples and exposes only the current interpreted
state and last event through the existing status boundary. `STILL`, `MOVING`,
four tilt directions, `SHAKE` and `IMPACT` are semantic observations only; no
PHOS behavior consumes them yet. Motion settings reload into the interpreter
without reopening the I2C provider.
