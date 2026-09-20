# Development Guide

## Local development

The application should support a development mode that does not require Raspberry Pi hardware.

Use interfaces and fakes/mocks for hardware.

## Configuration

Keep environment-specific values out of source code.

Prefer a configuration file plus environment variables for secrets.

Never commit API keys, passwords or tokens.

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

## Expression configuration

The existing frozen `RuntimeConfig` is the single application settings boundary.
`RuntimeConfig.from_file(Path(...))` loads ordinary JSON settings; `--config PATH`
uses it at startup. Explicit CLI arguments override file values; unspecified
fields keep dataclass defaults. Unknown keys (including secret-key fields) are
rejected. Model paths are relative to the process working directory. JSON arrays
become the existing tuple settings. See `config/expression-local.json` and
`config/expression-aws.json` for runnable examples. The existing local model
path, labels, dimensions, scale, mean, channel swap, grayscale and crop margin
remain supported through both configuration and CLI.

New top-level fields: `expression_provider` (`local`/`aws`, default `local`),
`expression_minimum_confidence` (0.60, additional floor on semantic thresholds),
and the nested `cloud_expression` object:

| Key | Default | Meaning |
| --- | --- | --- |
| `region` | null | SDK region; config overrides AWS_REGION, then SDK AWS_DEFAULT_REGION/profile |
| `cooldown_seconds` | 30 | Minimum interval between attempts |
| `stable_seconds` | 1 | Eligible local continuity required before cloud work |
| `refresh_seconds` | 60 | Refresh similar input before expiry |
| `cache_ttl_seconds` | 90 | Maximum age from sample capture |
| `max_requests_per_minute` | 2 | Enforced as minimum spacing, no bursts |
| `max_requests_per_session` | 0 | Optional cap; zero is unlimited |
| `change_threshold` | 0.08 | Mean absolute normalized thumbnail difference |
| `minimum_face_confidence` | 0.90 | Minimum AWS face detection confidence |
| `retry_initial_seconds` | 60 | First failure backoff |
| `retry_max_seconds` | 600 | Exponential backoff ceiling |
| `connect_timeout_seconds` | 3 | SDK connection timeout |
| `read_timeout_seconds` | 5 | SDK socket read timeout |

Durations/rates must be positive and finite; refresh must precede TTL, retry
maximum must be at least the initial delay, confidence/change values must be in
[0, 1], and session cap must be a nonnegative integer. A cooldown longer than TTL
is permitted but deliberately leaves periods with UNKNOWN evidence.
New CLI options: `--config`, `--expression-provider`, `--aws-region`.
Use JSON or Python configuration for all other cloud policy settings.

A future PHOS web configuration layer must read/change these same non-secret
settings and construct validated RuntimeConfig/CloudExpressionConfig values,
without changing Vision/provider implementations. Settings are currently applied
at startup (restart after editing); no web UI or live reconfiguration is present.
AWS credentials remain external to this configuration boundary and must never
become fields in normal web-editable application settings. Standard SDK profiles,
environment credentials or role credentials remain responsible for secrets.

AWS unit tests inject clients/SDK fakes and a clock, require no credentials and
make no network requests. Run `python3 -m pytest -q`; the OpenCV-specific local
preprocessing test is skipped when cv2/numpy are unavailable.
