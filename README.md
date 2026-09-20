# PHOS - Raspberry Pi Robot

Personal modular robot project targeting Raspberry Pi 3.

## Current hardware
- Raspberry Pi 3
- 5-inch 800x600 display
- Microphone

## Project principles
- Python first
- Modular architecture
- Hardware abstraction
- Test without hardware
- Incremental development
- Keep Raspberry Pi 3 constraints in mind

## Start here
1. Read `AGENTS.md`
2. Read `docs/architecture.md`
3. Read `docs/hardware.md`
4. Read `docs/roadmap.md`
5. Read `docs/decisions.md`

The `src/` tree is intentionally lightweight at the beginning. Add modules only when the feature requires them.

## Run PHOS

From the repository root in a graphical Raspberry Pi OS desktop session:

```bash
python3 src/robot/main.py --config config/phos.json
```

[config/phos.json](config/phos.json) is the single, editable configuration and
complete default example. It starts the fullscreen animated eyes with camera
and expression processing disabled. Omitting `--config` loads this same file
from the checkout. Press Ctrl+C to stop and Escape to leave fullscreen.

Edit the file, then restart using the same command:

- **Face tracking only:** set `vision.face_tracking_enabled` to `true`, keeping
  `expression.enabled` false. Install the camera/OpenCV dependencies first.
- **Local expressions:** set `expression.enabled` to `true` and
  `expression.provider` to `"local"`. The included `expression.local` settings
  describe MobileFaceNet; download the model following
  [installation](docs/installation.md). Images remain on the Pi.
- **AWS expressions:** set `expression.enabled` to `true` and
  `expression.provider` to `"aws"`. Install boto3 and configure external
  credentials/region using [AWS setup](docs/installation.md#optional-aws-expression-mode).
  **Selected face crops leave the Pi and are sent to AWS.**

Expressions automatically enable local tracking. For diagnosis set
`logging.expression_diagnostics` to `true`; check `PHOS configuration loaded`
and `Expression provider` in the logs. Cloud requests run independently of gaze
and rendering, with cache, rate limits and failure backoff. See
[Vision policy](docs/vision.md#cloud-request-and-evidence-policy) for cost and
confirmation timing. Both modes observe facial cues, not true internal emotions.

Malformed settings or missing active local model files fail before camera or
display startup. Paths inside JSON are relative to that JSON file's directory.
AWS credentials never belong in JSON. The old individual setting flags remain
only as deprecated overrides; migrate scripts to the command above.
The former expression-specific JSON files are replaced by `config/phos.json`.

The [configuration reference](docs/development.md#configuration) documents every
field, precedence and migration. The same typed validation and atomic persistence
are reusable by a future web interface; no web UI or live reload is implemented.

## Eye demo

Preview eyes independently from Vision:

```bash
python3 src/robot/ui/demo.py
```

Use keys `1`–`5` for neutral, happy, curious, surprised, and sleepy. Use arrow
keys to move the pupils; press `q` to close the demo.


## AI abstraction

The robot uses `LLMProvider` so the conversational brain can be OpenAI, Anthropic, a LAN model or another backend without changing robot behavior code. See `docs/ai.md`.

## Agent guidance

PHOS uses hierarchical repository instructions: start with `AGENTS.md`, then read any more-specific `AGENTS.md` under the subsystem being changed. Detailed architecture and accepted decisions live under `docs/`. The reusable Codex workflow skill is project-neutral and lives at `.codex/skills/architecture-first-coding-agent/SKILL.md`.
