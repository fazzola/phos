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

## Run the current robot runtime

From the repository root, run:

```bash
python3 src/robot/main.py
```

The current runtime starts the Core, `BehaviorEngine`, and a 30 FPS eye render
loop in a fullscreen Tkinter window on the HDMI display. Press `Ctrl+C` to
shut PHOS down cleanly; press `Escape` to leave fullscreen mode. Run it from a
graphical Raspberry Pi OS desktop session.

Enable the completed face-tracking milestone with the Pi Camera connected:

```bash
python3 src/robot/main.py --face-tracking
```

This uses Picamera2 plus the OpenCV Haar detector at 640×480 and moves the
pupils toward the largest detected face. It does not require or run an ONNX
expression model. Follow [the Raspberry Pi installation guide](docs/installation.md)
to install the camera and OpenCV dependencies. Without `--face-tracking`,
PHOS runs without camera access.

## Expression reactions

Expression reactions use the same camera/face tracking path and the ONNX Model
Zoo FER+ model downloaded during installation. It expects 1×1×64×64 grayscale
input and produces eight labels in a fixed order.

```bash
python3 src/robot/main.py \
  --expression-model models/expression/emotion-ferplus-8.onnx \
  --expression-labels neutral,happiness,surprise,sadness,anger,disgust,fear,contempt \
  --expression-input-size 64x64 \
  --expression-grayscale \
  --expression-scale 1 \
  --expression-mean 0,0,0 \
  --expression-no-swap-rb
```

The command converts the RGB camera crop to grayscale and supplies unscaled
pixels (`scale=1`), zero mean, and no channel swap, as required by this model.
It enables camera face tracking as well. See [Vision](docs/vision.md) for the
stable-observation policy and supported reaction behavior.

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
