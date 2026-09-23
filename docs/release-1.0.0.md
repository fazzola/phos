# PHOS 1.0.0 release record

**Status: source hardening completed; target acceptance and tagging blocked.**
The authoritative version is `robot.__version__` in `src/robot/__init__.py`, exactly
`1.0.0`. Packaging derives it; startup and Web Admin report it. The version string
is not evidence of physical acceptance. No commit, tag or publication was made.

## Included scope

- 800×600 animated eyes with blink/gaze, layered Canvas depth and named iris
  themes; BehaviorEngine mediates UI-neutral visual state.
- Local camera tracking and uncertain facial-expression observations with
  selectable local OpenCV/ONNX or optional AWS Rekognition providers.
- Optional local-display picture-in-picture using the same camera owner,
  latest in-memory frame, bounded encoding and configurable diagnostics.
- One strict canonical JSON schema, configuration-relative paths, atomic saves,
  authenticated domain editor, password rotation, revocable sessions and CSRF.
- Logging-level, iris-theme and preview reload through shared application
  services; confirmed restart through the documented user systemd service.

Voice/conversation, sensors, LEDs, Home Assistant, remote API, MCP and OS reboot
remain outside 1.0.0. See [roadmap](roadmap.md).

## Hardening changes

- Restored the committed preview default to **off**, matching eyes-only startup
  and avoiding accidental camera acquisition on a fresh install.
- Preview reload now acknowledges runtime/camera lifecycle acceptance before
  recording the preview configuration as active. Camera-start failure releases
  partially acquired resources and leaves the preview change pending.
- Preserved configuration-relative model/log paths during reload (the former
  dataclass replacement passed relative paths through constructor overrides).
- Cancelled/drained in-flight preview reloads and supervisor child waiters during
  shutdown; clear stopped-pipeline snapshots and avoid false Vision failure on
  intentional preview-only camera stop.
- Retained one encoder slot across rapid preview disable/enable cycles; a running
  job cannot be cancelled, so new work waits instead of growing a queue.
- Runtime failures now propagate nonzero exit status. Unexpected web-worker death
  stops the parent cleanly and also propagates failure for systemd recovery.
- Corrected partial-apply messages: earlier successful appearance changes remain
  recorded if preview application fails. Invalid schema still applies nothing.
- Consolidated fresh-install guidance and corrected stale preview/reload/recovery
  documentation. Functional deprecated CLI overrides and useful eye/paired-Vision
  diagnostics remain supported; they are not dead controls or independent files.

The preceding raw-PPM preview fix remains included, with once-per-failure-streak
logging. Preview now converts BGR to RGB for Tk presentation only. The legacy
detector/model color-order inconsistency remains documented in Vision; this
hardening does not silently change their preprocessing.

## Changed files

| Area | Files |
| --- | --- |
| Runtime/configuration | `config/phos.json`, `src/robot/lifecycle.py`, `src/robot/main.py`, `src/robot/runtime.py`, `src/robot/ui/display.py`, `src/robot/vision/pipeline.py`, `src/robot/web/server.py` |
| Regression tests | `tests/test_config.py`, `tests/test_lifecycle.py`, `tests/test_main.py`, `tests/test_runtime.py`, `tests/test_web.py`, `tests/ui/test_camera_preview.py`, `tests/vision/test_aws_expression.py` |
| Documentation | `README.md`, `docs/architecture.md`, `docs/current-state.md`, `docs/decisions.md`, `docs/development.md`, `docs/installation.md`, `docs/release-1.0.0.md`, `docs/roadmap.md`, `docs/vision.md`, `docs/web-administration.md` |

Existing CLI mocks were updated to accept the application-owned web supervisor;
assertions were retained. The runtime-failure test now requires an exception as
well as ERROR state and camera cleanup, verifying the nonzero-exit contract.

## Installation and configuration

Follow the single [fresh-install procedure](installation.md#phos-100-reproducible-installation):
Pi desktop/Python 3.11+, apt camera/OpenCV/Tk, source at `~/phos`, venv with system
packages, pinned web dependencies, optional model/SDK and external credentials,
validate the complete JSON, then install/start the user service. OpenCV DNN needs
no separate ONNX runtime. Exact commands and checksum are in that guide.

Production commands, from the desktop user after installation:

```bash
systemctl --user enable --now phos.service
systemctl --user status phos.service
systemctl --user restart phos.service
systemctl --user stop phos.service
journalctl --user -u phos.service -n 100 --no-pager
```

The service loads `%h/phos/config/phos.json` (normally `/home/pi/phos/config/phos.json`).
`RuntimeConfig` owns the schema: `web`, `display`, `behavior`, `vision`, `expression`,
`logging`; all fields are required, including inactive providers. Canonical defaults
and the complete example remain in that one file. Administrator hashes live in
`config/.phos-admin/`, outside JSON; AWS credentials use the external SDK chain.

| Live reload | Restart required |
| --- | --- |
| `logging.level` | Log destination and expression diagnostics |
| `display.iris_color` | Display geometry/FPS/fullscreen/transitions and all behavior settings |
| Every `vision.camera_preview` field | Tracking, capture geometry/cadences and detector settings |
| — | Every expression/provider/model/cloud-policy setting; web enable/address/port |

Save alone never applies runtime settings. Mixed reloads retain the restart-required
list. Password changes take effect immediately and revoke sessions. Restart
invalidates sessions, reloads the full saved JSON and returns web at the saved
address unless disabled. Manual launches do not support browser restart.

## Verification evidence

The current local audit uses macOS and Python 3.11.6, not Raspberry Pi hardware.
Full suite rechecked on 2026-09-23: **285 passed, 1 skipped, 2 failed** in 219.08 seconds. Final focused
lifecycle/UI checks: **58 passed**. Details are in
[current state](current-state.md#final-release-hardening).
The two real localhost-worker tests are blocked by sandbox socket binding;
permission to rerun outside the sandbox was declined. They remain failures, not
converted to skips or weakened tests. The OpenCV preprocessing test is skipped
because this environment lacks `cv2`.

Focused regression tests cover repeated preview-only start/stop, camera-start
rollback, shutdown during reload, relative paths, task cleanup, bounded encoder
work, nonzero runtime failure and worker-failure propagation. Existing tests cover
login/rotation/revocation, CSRF, every domain's field coverage/persistence, canonical
validation, provider selection, mixed reload and confirmed restart. AWS calls are
mocked; no paid/service requests were made.

`pip check`, source version/config validation, shell syntax, CLI help and diff
checks pass. A source archive with version 1.0.0 and required config/service/web
assets was built and inspected. Wheel/editable installation was not verified:
this environment lacks `wheel` (`bdist_wheel`). The old local venv contains a
0.1.0 installed distribution; source entry points and tests explicitly select
`src`, so it is not the release version. Production source launch does not need
that installed distribution. The tracked-file scan found no AWS access-key or
private-key patterns; credentials are not part of the schema or release archive.
This is a targeted scan, not a guarantee about external credentials or git history.

## Raspberry Pi 3 performance review

No fresh Pi CPU/RAM, display FPS or live AWS latency measurements were available.
Do not interpret configured rates as measurements:

| Component | Current evidence / concern |
| --- | --- |
| Eyes | Target 30 FPS at 800×600; lightweight layered Tk primitives, no 3D engine. Actual Canvas redraw FPS must be measured on the Pi. |
| Vision | Capture ceiling 15 FPS, detection 4 Hz, expression inference 3 Hz. Work and cadence alignment lower actual throughput; these are separate from the eye loop. |
| Local model | Historical Pi synthetic MobileFaceNet forward p50/p95 114.83/123.51 ms; later paired camera forwards roughly 127–138 ms. Excludes full runtime rendering/capture and is not new release evidence. |
| Preview | Off by default; ceiling 5 FPS at 25% display width (200×150 for a 640×480 camera). One retained snapshot plus one encoding job; no recording/network video. |
| AWS | Single-flight worker, cache/backoff and default maximum two requests/minute; external latency and credential acquisition need actual service checks. |
| Web | Separate process, two Waitress threads and bounded requests/sessions. Password hashing can consume Pi CPU during login; measure while eyes/Vision run. |

The historical model test recorded undervoltage/throttling (`0x50005`); resolve
power/thermal conditions before calling performance acceptable. See
[measurement context](vision-model-evaluation.md#verified-evidence) (the timings table
and accompanying Pi conditions). Keep preview, expressions, web and tracking
opt-in; keep neutral reactions and verbose diagnostics off by default. For long
service runs, consider `logging.file: null` and the system journal: the optional
plain log file is not rotated by PHOS. No speculative optimization was added.

## Release checklist

A checked box means the stated automated/documentary check is complete. It does
not substitute for a physical acceptance result. Record OS, commit, model hash,
service logs, observations and timing alongside each Pi check.

- [x] Authoritative version 1.0.0; source archive includes canonical config and web/service assets.
- [x] One fresh-install path, required packages, external credentials and service commands documented.
- [x] Canonical validation/save, config-relative paths and all editable domains covered by tests.
- [x] First-login gate, password change, logout/session revocation and CSRF covered by tests.
- [x] Eye geometry/behavior, iris reload, preview lifecycle and mixed reload/restart classification covered by tests.
- [x] Tracking, local/AWS provider selection, failure/backoff and semantic pipeline covered without real AWS calls.
- [x] Runtime shutdown/cancellation, worker failure and service exit-code contract covered by tests.
- [x] Documentation synchronized; no new roadmap feature, commit, tag or publication.
- [ ] Complete full suite with localhost binding and OpenCV available; zero unexplained failures/skips.
- [ ] Install from a clean Pi OS desktop using only the installation guide; verify dependency imports/model checksum.
- [ ] First login, password change and every page from actual phone/tablet; save/reject invalid input and stale tabs.
- [ ] Run 800×600 eyes for at least 10 minutes; measure FPS/CPU/RSS with tracking/preview on and off.
- [ ] Reload iris while eyes animate; reload logging; combine with a pending provider/FPS change and confirm restart-required survives.
- [ ] Track/lose/reacquire a face; verify bounded gaze and no stale preview frame after stopping the camera.
- [ ] Run local expressions with the real model; verify UNKNOWN abstention and the intended happy/surprise behavior. Accuracy remains unestablished.
- [ ] With an authorized AWS account, verify requests/latency/limits and network failure without disrupting local tracking/eyes.
- [ ] Toggle preview repeatedly; check actual image visibility, colors, corners, scale, face box/labels and maximum FPS on the Pi display.
- [ ] Confirm desktop-login systemd startup, Web Admin Restart PHOS, fresh PID/config, new login and return of display/Vision/web.
- [ ] Stop/start and SIGTERM during camera/AWS activity; confirm port/camera release and no surviving service processes.
- [ ] Exercise failure recovery/start limit; confirm the service returns after correcting the cause.

## Remaining blockers and limitations

Do **not** tag `v1.0.0` based on this local audit alone. Remaining blockers are the
full test run with required capabilities, clean-Pi installation/systemd/display
acceptance, combined hardware stability/performance and local/AWS behavior checks.
Expression quality and camera channel order remain explicit limitations requiring
physical verification, not claims of emotion inference. Web is trusted-LAN HTTP,
not Internet/TLS or multi-user administration; status is configuration metadata,
not a live subsystem-health dashboard. A lifecycle IPC timeout can leave an
in-flight operation completed but unacknowledged; local inspection and PHOS
restart restore the retired channel. The service depends on a real graphical
session, and its 20-second shutdown deadline can terminate a stuck native/SDK call.
