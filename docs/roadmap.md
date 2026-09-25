# PHOS roadmap

## PHOS 1.0.0 — scope frozen

The established baseline is the complete 1.0.0 scope; see the
[release record](release-1.0.0.md). Do not expand it during hardening.

- [x] Raspberry Pi runtime, animated eyes, visual state/behavior and independent rendering
- [x] Camera face tracking and bounded gaze via BehaviorEngine
- [x] Facial-expression observations/reactions with local ONNX or optional AWS
- [x] Canonical JSON model, validation and atomic persistence
- [x] Authenticated web administration, mandatory bootstrap password change and external secrets
- [x] Eight configuration domains with isolated page saves and read-only status
- [x] Release version, installation/user documentation and hardware-free regression tests
- [x] Validated logging-level, iris and camera-preview reload; confirmed supervisor-owned PHOS restart
- [x] Release hardening for failure propagation, preview lifecycle cleanup and bounded preview work
- [ ] Verify user systemd restart and display-session environment on the actual Pi
- [ ] Repeat the complete release acceptance sequence on the Pi after these changes
- [ ] Establish expression accuracy and calibrate neutral reactions on actual hardware
- [ ] Verify optional AWS behavior/latency and mobile/tablet LAN administration on the Pi

The hardware document records the display and Pi Camera/tracking as already
operational. Fresh release regression and expression-quality verification remain
separate from that prior evidence. See the release record for exact checks.

## Approved follow-on — BME280 / BMP280

- [x] Optional BME280 and BMP280 I2C adapters and provider-neutral environmental service.
- [x] Canonical environmental type selector, restart-only policy, authenticated Sensors editor and live snapshot with explicit capabilities.
- [x] Hardware-free adapter/service/configuration/web regression coverage and setup documentation.
- [ ] Verify actual breakout wiring/address, real units/accuracy, recovery and concurrent eyes/Vision responsiveness on Raspberry Pi 3.

This explicitly requested addition does not reopen the frozen release scope or
establish hardware acceptance. Sensor-driven behavior remains deferred.

## Approved follow-on — CCS811 air quality

- [x] Optional smbus2 CCS811 adapter with eCO2/TVOC, conditioning and error checks.
- [x] Shared sensor worker/lifecycle, canonical settings and Web Admin status/editor.
- [x] Service-level environmental compensation with safe missing-humidity handling.
- [x] Fake bus/provider tests and installation/configuration documentation.
- [ ] Verify actual module power/logic/wake wiring, both addresses as fitted, first-use stability, clock stretching and concurrent operation on Pi 3.
- [ ] Consider baseline persistence after physical validation; not implemented now.

## Approved follow-on — GY-521 / MPU-6050 IMU

- [x] Optional smbus2 MPU-6050 adapter with typed six-axis readings and bounded worker lifecycle.
- [x] Canonical configuration, Web Admin editor/status and hardware-free adapter/runtime tests.
- [x] Provider-neutral, debounced motion interpretation with live-reloadable thresholds.
- [x] Motion-state behavior mapping to FaceState with live-reloadable visual intensity and timing; no LED behavior.
- [ ] Verify board wiring, address, stable readings and coexistence on Raspberry Pi 3.

## Post-1.0 — explicitly deferred

| Area | Deferred work |
| --- | --- |
| Environmental/inertial sensors | Behavior integration for sensors including MPU-6050 and BME280; CCS811 eCO2 must not be labeled direct CO2. |
| LED ring | WS2812B electrical verification, adapter and behavior mapping. |
| Remote-control API | Authenticated service-mediated control, authorization and documented contracts. |
| Advanced OS administration | Raspberry Pi reboot, if a future safe permission boundary is approved. |
| MCP server | Service-mediated tools; no direct hardware or subsystem-internal access. |
| STT | Microphone capture, VAD and speech recognition. |
| TTS | Provider-neutral synthesis, playback and speaker verification. |
| Conversational LLM | End-to-end conversation through LLMProvider; existing skeletons are not a delivered conversation feature. |
| Home Assistant | Integration/tool layer and explicit permissions; not the reasoning core. |

Future Web/API/MCP/Voice adapters must reuse PHOS application services for
validation, authorization, configuration and behavior commands. They must not
access GPIO, hardware drivers or subsystem internals directly. Extend services
when a capability is approved; do not create parallel control implementations.

Existing ahead-of-scope AI/voice scaffolding is preserved. Implement one approved,
runnable vertical capability at a time; do not start deferred work automatically.
