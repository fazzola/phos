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

Vision starts when `RuntimeConfig` is given an ONNX model path and matching
model labels. Without those model-specific settings, PHOS runs in development
mode without camera access.

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
