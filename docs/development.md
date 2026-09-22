# Development Guide

## Local development

The application should support a development mode that does not require Raspberry Pi hardware.

Use interfaces and fakes/mocks for hardware.

## Configuration

`config/phos.json` is the **single canonical configuration and complete example**.
The complete JSON structure and authoritative default values are in
[the file itself](../config/phos.json); edit it directly and restart PHOS:

```bash
python3 src/robot/main.py --config config/phos.json
```

No separate example/provider files or hidden JSON overlays are loaded. With no
argument, startup resolves that same file relative to the source checkout, not
its working directory. A custom `--config` selects one complete file instead.
To keep a separate deployment copy, copy the full canonical file, edit it and
pass its path explicitly. Keep deployment changes out of commits if inappropriate.
No file may contain credentials.

The six required sections are `web`, `display`, `behavior`, `vision`, `expression`
(with `smoothing`, `local`, `aws`) and `logging`. `vision` includes `detector`.
There are no speculative runtime/voice/sensor sections. Every field in the
canonical file is required, including null values and inactive-provider settings;
a missing value is an error, not a second default hidden in code.

### Field reference

Values/defaults are maintained only in `config/phos.json`. All numeric values
must be finite; booleans must be JSON booleans, not strings or numbers.

| Section | Fields and purpose |
| --- | --- |
| `web` | `enabled`: start the administration worker; `host`: IPv4/IPv6 bind address; `port`: integer 1–65535. See the [web manual](web-administration.md). |
| `display` | `width`, `height`: positive integer pixel dimensions; `fps`: positive integer display cadence; `fullscreen`: fullscreen startup; `transition_seconds`: positive renderer interpolation duration; `iris_color`: one of cyan, blue, green, turquoise, amber, violet or white. Iris theme is a renderer style choice and applies after validated configuration reload. |
| `behavior` | `blink_interval_seconds`, `gaze_interval_seconds`: positive ascending `[minimum, maximum]` timing ranges; `face_gaze_smoothing`: gaze smoothing coefficient in (0,1]; `reaction_decay_per_second`: positive visual reaction decay. |
| `vision` | `face_tracking_enabled`: camera/tracking without expression inference; `camera_resolution`: positive integer `[width,height]`; `capture_fps`, `detection_fps`: positive capture/detection cadences. `camera_preview` controls optional display-only picture-in-picture, disabled by default; all its fields (enabled, corner position, scale 0.1–0.4, maximum FPS 1–10 and three diagnostic toggles) are live-reloadable. |
| `vision.detector` | `cascade_path`: custom readable Haar file or null for existing platform discovery; `scale_factor`: pyramid scale greater than 1; `min_neighbors`: nonnegative integer detection support; `min_size`: positive pixel pair no larger than the camera resolution. |
| `expression` | `enabled`: expression processing, also enabling local tracking; `provider`: local/aws; `inference_fps`: positive local inference/cloud polling cadence; `crop_margin`: extra square-crop margin per side in [0,0.5]. |
| `expression.smoothing` | `minimum_confidence`: additional evidence floor in [0,1]; `minimum_observations`: positive integer count of distinct samples; `local_maximum_gap_seconds`: positive maximum gap for local evidence; `neutral_enabled`: enable neutral perception only after calibration. Cloud maximum gap is derived from its TTL. |
| `expression.local` | `model_path`: ONNX path or null; `labels`: unique, nonempty strings in output order (array may be empty only when local inference is inactive); `input_size`: positive `[width,height]`; `scale`: positive preprocessing multiplier; `mean`: three finite channel means; `swap_rb`: swap BGR/RGB; `grayscale`: existing grayscale preprocessing. When grayscale is true, provider behavior ignores swap_rb. |
| `expression.aws` | `region`: nonempty region string or null for external SDK/environment resolution; no credentials. |
| `expression.aws` | `cooldown_seconds`: minimum request interval; `stable_seconds`: eligible local continuity before requesting; `refresh_seconds`: refresh unchanged input; `cache_ttl_seconds`: maximum sample age. All positive; refresh must be less than TTL. |
| `expression.aws` | `max_requests_per_minute`: positive rate implemented as minimum spacing; `max_requests_per_session`: nonnegative integer cap, zero means unlimited; `change_threshold`: normalized crop difference threshold in [0,1]; `minimum_face_confidence`: AWS face-confidence floor in [0,1]. |
| `expression.aws` | `retry_initial_seconds`, `retry_max_seconds`: positive backoff limits, maximum at least initial; `connect_timeout_seconds`, `read_timeout_seconds`: positive SDK timeouts. |
| `logging` | `level`: DEBUG/INFO/WARNING/ERROR/CRITICAL; `file`: output path or null for console only; `expression_diagnostics`: detailed Vision/cloud diagnostics. SDK debug output is suppressed to avoid exposing request/credential metadata. |

All JSON paths resolve relative to the selected JSON file's directory. The
canonical local path therefore starts with `../models/`, and its log path points
back to the checkout root. Active local models and explicit active cascades must
be readable files. Inactive models need not exist; AWS mode needs no ONNX file.
The log parent must already exist and be writable. PHOS does not create arbitrary
configuration/model/log directories. ONNX content/model-output compatibility and
physical device availability still require runtime verification.

### Provider examples

Edit these fields **inside the complete file**, preserving the other fields.
These are illustrative fragments, not additional partial configuration files:

```json
{"expression": {"enabled": true, "provider": "local"}}
```

The canonical `expression.local` block already contains the MobileFaceNet input
contract. Download its model using [installation](installation.md). For FER+
rollback use the block in [Vision](vision.md), replacing every preprocessing
field rather than depending on former CLI defaults.

```json
{"expression": {"enabled": true, "provider": "aws"}}
```

Keep the existing `expression.aws` block; optionally edit region and request
policy. No fallback is supported. All camera selection/cropping stays local;
AWS receives selected crops only. See [Vision](vision.md) for privacy and policy.
AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY and, for temporary credentials,
AWS_SESSION_TOKEN are external environment credentials. AWS_REGION /
AWS_DEFAULT_REGION, shared SDK profiles and roles are also supported.
A null JSON region defers resolution to the external environment/SDK. Parsing
never imports boto3, searches for credentials or contacts AWS.

### Validation, precedence and migration

Startup reads one JSON, applies explicit deprecated CLI overrides, validates
schema/types/ranges and active paths, then builds typed settings and constructs
subsystems. Errors name the field or JSON line/column and exit with status 2
before camera/display startup. Duplicate keys, unknown keys (including secrets),
missing sections/fields and incompatible refresh/TTL or detector/camera sizes
are rejected. Finite numeric validation also rejects NaN/infinity.

Precedence: explicit legacy CLI value > selected JSON value. CLI values have no
independent defaults and never overwrite the file. `--expression-provider` or
`--expression-model` also enables expression processing for compatibility;
`--face-tracking` enables tracking without changing expression enablement.
`--aws-region` overrides JSON region, followed by AWS_REGION, then the standard
SDK AWS_DEFAULT_REGION/profile fallback. CLI model paths retain their old
working-directory-relative interpretation; JSON paths are config-relative.

Retained but deprecated: `--face-tracking`, `--expression-provider`,
`--aws-region`, `--expression-model`, `--expression-labels`,
`--expression-input-size`, `--expression-scale`, `--expression-mean`,
`--expression-no-swap-rb`, `--expression-grayscale`, `--expression-debug`,
`--expression-crop-margin`. Help and startup warn about this transition.
`--config` and `--help` remain the supported primary interface. No runtime flags
were removed in this migration. Migrate launch scripts now; remove compatibility
flags only in a separately announced breaking change after consumers migrate.

The old partial flat JSON format and `config/expression-local.json` /
`config/expression-aws.json` are retired. To migrate, start from `config/phos.json`:

| Former field(s) | Canonical destination |
| --- | --- |
| `display_fps`, `fullscreen` | `display.fps`, `display.fullscreen` |
| `face_tracking_enabled`, `camera_resolution` | same names under `vision` |
| `vision_capture_fps`, `face_detection_fps` | `vision.capture_fps`, `vision.detection_fps` |
| `expression_provider` | `expression.provider`; set `expression.enabled` explicitly |
| `expression_inference_fps`, `expression_crop_margin` | `expression.inference_fps`, `expression.crop_margin` |
| `expression_minimum_confidence` | `expression.smoothing.minimum_confidence` |
| `expression_model_path`, `expression_labels`, `expression_input_size`, `expression_scale`, `expression_mean`, `expression_swap_rb`, `expression_grayscale` | `expression.local` with the `expression_` prefix removed |
| `cloud_expression` | `expression.aws` (same member names) |
| `expression_diagnostics` | `logging.expression_diagnostics` |

The current runtime previously combined flat dataclass defaults, CLI overrides,
provider configuration, renderer/behavior/detector constructor defaults and
hard-coded logging setup. Composition now passes all applicable settings
explicitly from the canonical file. Standalone library/demo/benchmark constructor
fallbacks remain for compatibility, but are not application configuration sources.
Geometric face association gates, class-specific semantic safeguards, visual
profiles and SDK JPEG implementation details remain implementation constants.
No AI/voice settings are added for subsystems outside this runtime milestone.

### Reusable configuration API and web layer

`robot.config.RuntimeConfig` is the existing typed surface moved out of runtime;
`robot.runtime.RuntimeConfig` remains import-compatible. Cloud settings retain
`CloudExpressionConfig`, re-exported from the AWS adapter for existing callers.
JSON section names are mapped to typed fields at the boundary; raw dictionaries
never reach providers or behaviors.

- `load_document(path)` reads JSON for an editor without hardware/SDK imports.
- `RuntimeConfig.from_file(path)` loads and validates a full file.
- `RuntimeConfig.from_dict(document, base_dir=...)` validates edited settings
  with the same schema/rules, including config-relative paths.
- `config.to_dict()` returns the full serializable non-secret structure.
- `config.save(path)` validates and atomically replaces a file, rebasing paths
  if the file moves; a failed validation preserves the old file.

Existing `RuntimeConfig(**overrides)` and `CloudExpressionConfig(**overrides)`
Python calls overlay the canonical file for compatibility; they contain no
independent numeric defaults. Runtime construction revalidates before hardware
starts. New application code should use full-file/dict loading instead.

The optional [web administration adapter](web-administration.md) reuses this
read/edit/validate/save boundary. It never accepts/stores/displays AWS credentials
as normal settings. Its separate password store is not runtime configuration.
Save does not apply settings. The lifecycle service can reload logging level,
`display.iris_color` and all `vision.camera_preview` fields through runtime and
display boundaries; other persisted changes require restart.
The editor may call `from_dict(..., check_paths=False)` to repair a removed model
path; schema/types/ranges are still validated. Startup and saves always validate
active paths.
`robot.web.domains` maps canonical field paths into navigation and presentation
only. Page saves merge the selected area's fields into the full document, reject
out-of-area fields and run normal full-document validation/atomic persistence.
The registry defines no defaults, types or validation rules. New implemented
settings must be assigned to a domain; coverage tests require every canonical
field to appear exactly once. Read-only General/Status pages cannot save settings.
New non-secret runtime options must extend this canonical model/file, not add
standalone CLI arguments or another configuration mechanism.

## Dependencies

Before adding a dependency, consider:
1. Is the standard library sufficient?
2. Is the dependency maintained?
3. Does it work on Raspberry Pi 3?
4. Does it materially simplify the implementation?

## Testing

Test:
- state transitions
- event handling
- AI tool contracts
- hardware adapters through fakes
- error handling

Do not make ordinary unit tests depend on physical GPIO/audio/display hardware.

For web development install `.[web]` plus pytest in a virtual environment and
run `python -m pytest -q`. Web tests exercise real password hashing, CSRF,
configuration persistence and an isolated local WSGI worker without hardware.

## Release version and installation

`robot.__version__` in `src/robot/__init__.py` is authoritative. Setuptools derives
metadata from that literal; do not add another independently maintained version.
Source checkouts use `config/phos.json`; wheels install that same source document
under the environment's `share/phos/config/` data directory. Explicit `--config`
remains the supported deployment boundary; no alternate schema is introduced.
The pinned Python 3.11+ web snapshot is `requirements-web.txt`; platform camera
dependencies remain managed by Raspberry Pi OS. See the release record.


`robot.lifecycle` is the reusable lifecycle policy boundary. Its fixed operations
are status/reload/restart; it never accepts arbitrary commands or configuration
paths from callers. The web worker uses `robot.lifecycle_channel` to reach the
parent-owned service. Confirmation/authentication remain adapter responsibilities;
validation and restart capability policy are shared. Test both the service and
adapter guards. Infrastructure service markers are deployment metadata, not
ordinary JSON settings. No new runtime configuration section is needed.
