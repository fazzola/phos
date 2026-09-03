# Hardware

## Installed / available

| Component | Current state | Notes |
|---|---|---|
| Raspberry Pi | Available | Raspberry Pi 3 |
| Display | Available | 5 inch, 800x600 |
| Microphone | Available | Exact model/interface TBD |
| Speaker | Planned | Not yet specified |
| Raspberry Pi Camera | Planned / Vision target | Exact model/interface and physical availability TBD |
| LEDs | Planned | Not yet specified |
| Servos/motors | Planned | Not yet specified |
| Sensors | Planned | Not yet specified |

## Rules

- Record new hardware here when it becomes part of the project.
- Never assume an exact model, GPIO pin or protocol without documentation.
- Hardware-specific implementation belongs under `src/robot/hardware/`.
- Use mocks/fakes in tests.

## Open questions

- Display interface: TBD
- Display driver/library: TBD
- Microphone interface: TBD
- Audio output hardware: TBD
