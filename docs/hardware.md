# Hardware

This document records the physical hardware that is part of PHOS or has been selected for a future integration milestone.

Hardware listed here does **not** imply that its software integration is already implemented. Software behavior, providers, events, state mapping, and runtime integration must be designed separately before code is added.

## Installed / available

| Component             | Current state        | Interface / power                                      | Intended role                                                          | Notes                                                                                |
| --------------------- | -------------------- | ------------------------------------------------------ | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| Raspberry Pi          | Available            | Raspberry Pi 3                                         | Main PHOS computer and hardware controller                             | Primary target platform                                                              |
| Display               | Available / working  | 5 inch, 800x600                                        | PHOS face / eyes                                                       | Exact electrical/display interface should remain documented from the real build      |
| Microphone            | Available            | Exact model/interface TBD                              | Future voice input                                                     | Exact model/interface still to document                                              |
| Speaker               | Planned              | TBD                                                    | Future voice output                                                    | Not yet specified                                                                    |
| Raspberry Pi Camera   | Available / working  | Raspberry Pi camera interface                          | Vision and face tracking                                               | Already used by the current PHOS Vision stack                                        |
| BME280                | Available / selected | I2C preferred; SPI also supported by the sensor        | Ambient temperature, relative humidity, atmospheric pressure           | Intended to be connected directly to the Raspberry Pi                                |
| Keyestudio SEN-CCS811 | Available / selected | I2C                                                    | Air-quality sensing: eCO2 and TVOC                                     | CCS811 reports **equivalent CO2 (eCO2)**, not direct NDIR CO2 measurement            |
| GY-521 (MPU-6050)     | Available / selected | I2C                                                    | 6-axis inertial sensing: 3-axis acceleration + 3-axis angular velocity | Intended for future motion/orientation awareness; exact software use not defined yet |
| WS2812B RGB LED ring  | Available / selected | Single-wire addressable data; typically 5 V LED supply | Visual status / state indication through color and animation           | LED count, GPIO assignment, power budget, and physical placement still TBD           |
| Servos/motors         | Planned              | TBD                                                    | Future physical movement                                               | Not yet specified                                                                    |

## Environmental sensors

### BME280

PHOS will include a BME280 connected directly to the Raspberry Pi.

Measurements:

- temperature;
- relative humidity;
- atmospheric pressure.

Preferred connection for PHOS: **I2C**, unless a later hardware constraint makes SPI preferable.

The BME280 should eventually be exposed to the rest of PHOS through a hardware-neutral sensor abstraction. No behavior should be assigned to these measurements in this document.

Possible future uses include environmental awareness, status reporting, Home Assistant exposure, and behavior/context inputs. These are future software decisions and are not part of the current hardware milestone.

### Keyestudio SEN-CCS811

PHOS will include a Keyestudio SEN-CCS811 connected directly to the Raspberry Pi over **I2C**.

Measurements provided by the CCS811 family:

- eCO2 (equivalent CO2);
- TVOC (total volatile organic compounds).

Important semantic rule: PHOS documentation and future UI/API names must not describe CCS811 eCO2 as a direct physical CO2 measurement. It is an estimated/equivalent CO2 value derived by the sensor.

The exact Keyestudio module revision, supply requirements, pin labels, and I2C address/configuration must be verified from the physical board before GPIO wiring is finalized.

### Shared I2C bus

BME280 and CCS811 are expected to share the Raspberry Pi I2C bus if their actual module configuration and addresses are compatible.

Before integration:

- verify the exact I2C addresses of both physical modules;
- verify module voltage requirements and whether each breakout includes regulation/level shifting;
- document the Raspberry Pi pins used for SDA, SCL, power, and ground;
- verify that I2C is enabled on Raspberry Pi OS;
- avoid assigning addresses or GPIO pins in software documentation until verified on the real hardware.

## Inertial sensor

### GY-521 (MPU-6050)

PHOS will include a GY-521 module based on the MPU-6050, connected directly to the Raspberry Pi over **I2C**.

The device provides six inertial measurement axes:

- 3-axis accelerometer: X, Y, Z linear acceleration;
- 3-axis gyroscope: X, Y, Z angular velocity / rotation rate.

The module may later be used to give PHOS awareness of its own movement, tilt, orientation changes, vibration, or physical interaction. Those behaviors are intentionally **not defined yet** and belong to a later software-integration milestone.

Important distinction: the MPU-6050 measures acceleration and angular velocity. Absolute orientation is not a direct raw sensor output and would require software-side estimation/filtering if needed later.

Before integration:

- verify the exact GY-521 board revision and pin labels;
- verify its supply and logic-level requirements on the actual breakout board;
- verify the configured I2C address (commonly dependent on the AD0 pin state);
- document whether AD0, INT, or other auxiliary pins will be used;
- verify coexistence with the BME280 and CCS811 on the shared I2C bus;
- do not define gesture, orientation, impact, or movement semantics until the corresponding PHOS behavior contract is designed.

## WS2812B RGB LED ring

PHOS will include a WS2812B addressable RGB LED ring for visual feedback in addition to the face displayed on screen.

Intended role:

- communicate PHOS states through color;
- provide short visual reactions;
- provide activity/attention feedback;
- potentially complement states such as listening, thinking, speaking, sleeping, warning, or error.

The mapping between colors/animations and PHOS states is **not defined yet** and belongs to a later behavior/integration decision.

### Electrical considerations

WS2812B LEDs are normally powered from a 5 V supply and can draw significant current depending on LED count and brightness.

Before wiring the ring:

- determine the exact number of LEDs in the ring;
- calculate the required 5 V power budget;
- do not assume the Raspberry Pi 5 V rail is suitable for the final LED load;
- ensure the Raspberry Pi and LED power supply share a common ground;
- verify whether a 3.3 V to 5 V logic-level shifter is required for reliable data signaling;
- select and document the final GPIO only after checking compatibility with the chosen Raspberry Pi LED driver/library;
- consider the usual WS2812B data-line protection and supply decoupling recommended for the final wiring.

Brightness should eventually be limited in software both for power consumption and to avoid excessive visual intensity, but that behavior is not part of this hardware document.

## Hardware/software boundary

Directly connected hardware does not belong directly inside BehaviorEngine, Vision, LLM, or UI code.

Future integrations should preserve this direction:

```text
Physical sensor / LED hardware
        ↓
Hardware-specific driver/provider
        ↓
Provider-neutral reading or command
        ↓
PHOS core / state / behavior integration
```

Examples of future abstractions may include environmental sensor readings and an addressable-light output interface, but their exact APIs must be decided when those milestones begin.

The current hardware update does **not** authorize implementation of those abstractions yet.

## Wiring information still to record

The following details must be filled in after verifying the physical components:

- BME280 exact breakout/module revision;
- BME280 I2C address on the actual board;
- CCS811 exact Keyestudio module revision;
- CCS811 I2C address/configuration on the actual board;
- GY-521 exact breakout/module revision;
- MPU-6050 I2C address / AD0 configuration;
- whether the MPU-6050 INT pin will be used;
- Raspberry Pi SDA/SCL pins used in the final build;
- sensor power/logic voltage for the exact breakout boards;
- WS2812B ring LED count;
- WS2812B external power-supply specification;
- WS2812B data GPIO;
- logic-level shifter choice, if required;
- final connector/wiring scheme;
- microphone interface;
- audio output hardware.

## Rules

- Record new hardware here when it becomes part of PHOS.
- Distinguish **selected/available hardware** from **software-integrated hardware**.
- Never assume an exact module revision, GPIO pin, I2C address, supply voltage, or protocol detail without verifying the real component.
- Hardware-specific implementation belongs under `src/robot/hardware/` unless the repository architecture explicitly establishes a different location.
- Application subsystems must not depend directly on Raspberry Pi hardware libraries.
- Use provider-neutral interfaces between hardware drivers and PHOS core logic.
- Use mocks/fakes for hardware-dependent tests.
- Do not make new sensors influence PHOS behavior until that behavior has been explicitly designed and documented.
- Do not assign semantic LED colors/states until the LED behavior contract has been explicitly designed.

## Current hardware milestone status

Already operational:

- Raspberry Pi 3 runtime;
- 800x600 PHOS display/eyes;
- Raspberry Pi Camera and face tracking.

Selected for the next hardware-integration planning phase, but **not yet integrated in software**:

- BME280;
- Keyestudio SEN-CCS811;
- GY-521 (MPU-6050);
- WS2812B RGB LED ring.
