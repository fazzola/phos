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
| BME280 | Software integrated; physical acceptance pending | I2C bus 1, 3.3 V logic | Temperature, relative humidity, atmospheric pressure | Exact breakout/address still to verify |
| Keyestudio SEN-CCS811 | Software integrated; physical acceptance pending | I2C                                                    | Air-quality sensing: eCO2 and TVOC                                     | Software integrated; physical acceptance pending; eCO2 is not direct NDIR CO2            |
| GY-521 (MPU-6050)     | Available / selected | I2C                                                    | 6-axis inertial sensing: 3-axis acceleration + 3-axis angular velocity | Intended for future motion/orientation awareness; exact software use not defined yet |
| WS2812B RGB LED ring  | Available / selected | Single-wire addressable data; typically 5 V LED supply | Visual status / state indication through color and animation           | LED count, GPIO assignment, power budget, and physical placement still TBD           |
| Servos/motors         | Planned              | TBD                                                    | Future physical movement                                               | Not yet specified                                                                    |

## Environmental sensors

### BME280

PHOS supports a BME280 through `robot.hardware.bme280.BME280Provider` and the
provider-neutral environmental service. Web Admin → Sensors shows temperature
in °C, relative humidity in %, and station pressure in hPa (not sea-level adjusted).
It does not affect behavior, eyes or Vision. Software tests use fakes; the exact
breakout and physical installation have **not** been verified.

Expected wiring for a **3.3 V-compatible I2C breakout**, with the Pi powered off:

| Breakout signal | Raspberry Pi 3 physical header pin | Function |
| --- | --- | --- |
| 3.3 V-compatible supply input | 1 | 3.3 V |
| GND | 6 | Ground |
| SDA | 3 | GPIO2 / SDA1 |
| SCL | 5 | GPIO3 / SCL1 |

These are expected signal connections, not a claim about your module's pin order
or VIN regulator. Check its schematic/labels before wiring. Pi GPIO uses 3.3 V
logic; do not pull SDA/SCL up to 5 V. The bare BME280 supply is 1.71–3.6 V,
with VDDIO 1.2–3.6 V; a breakout may add a regulator or level shifter, which must
be checked independently. For exposed CSB/SDO, follow the board schematic:
CSB high selects I2C; SDO low selects 0x76, high selects 0x77. Do not leave SDO
floating or assume the breakout has particular pull-ups. Sources:
[Bosch datasheet](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme280-ds002.pdf),
[driver wiring reference](https://bme280.readthedocs.io/en/latest/#gpio-pin-outs).

PHOS uses `/dev/i2c-1` and the configured `sensors.environmental.i2c_address` string,
`"0x76"` or `"0x77"`. It does not scan or silently fall back to another address.
The selected adapter checks register 0xD0: BME280 requires chip ID 0x60,
BMP280 requires 0x58. A mismatched chip is unavailable; there is no automatic
switch to another type. See [setup and bus verification](installation.md#optional-environmental-sensor).
Place the sensor away from Pi/display heat and check readings against a reference;
no enclosure-heating correction or calibration offset is applied.

### BMP280

PHOS also supports BMP280 through `robot.hardware.bmp280.BMP280Provider`, using
exactly the same environmental service and I2C bus ownership as BME280. Select
one sensor in **Web Admin → Sensors → Type**, save and Restart PHOS. BMP280
measures temperature (°C) and station pressure (hPa); it has **no humidity
sensor**. Its reading contains `humidity_percent: null`; the UI says **Not
supported**, never 0%. Both adapters publish explicit available measurements.

The 3.3 V-compatible I2C wiring assumptions in the BME280 table above apply to
BMP280 breakouts too; confirm the actual board schematic and pin labels. Address
is configurable as 0x76 or 0x77. Power off before changing modules. Follow the
single [installation procedure](installation.md#optional-environmental-sensor)
for dependencies, bus enablement and verification. Real BMP280 acceptance is pending.

### Keyestudio SEN-CCS811

PHOS supports CCS811 through `hardware.ccs811.CCS811Provider` and the shared
sensor worker/lifecycle. It reports **eCO2 (estimated equivalent CO2), ppm**, and
**TVOC (total volatile organic compounds), ppb**. eCO2 is inferred from gas
sensor response, **not a direct NDIR CO2 measurement**. It is independent of
BME280/BMP280 and can run alongside either. No behavior or display-eye reactions
are attached to these observations. Physical module acceptance remains pending.

The exact board revision called SEN-CCS811 must be identified before wiring.
The [Keyestudio KS0457 reference](https://wiki.keyestudio.com/KS0457_keyestudio_CCS811_Carbon_Dioxide_Air_Quality_Sensor)
specifies **5 V module power**; do not confuse module VCC with bare-chip supply
or assume its SDA/SCL pull-ups are Pi-compatible. Confirm the regulator, pull-ups
and level shifting on the actual breakout. Pi-side SDA/SCL must use **3.3 V
logic**; if the module side is 5 V, use suitable bidirectional I2C level shifting.
Power off before wiring.

| Module signal | Raspberry Pi 3 physical pin / connection |
| --- | --- |
| GND | Pin 6, shared ground |
| SDA | Pin 3 / GPIO2 / SDA1, at Pi-compatible logic level |
| SCL | Pin 5 / GPIO3 / SCL1, at Pi-compatible logic level |
| VCC | For confirmed KS0457 5 V input: pin 2 (5 V); only a verified 3.3 V-compatible breakout may use pin 1 instead |
| nWAKE / WAK, if exposed | GND (or confirm the board already holds it low); PHOS does not drive a wake GPIO |
| nRESET, if exposed | Keep deasserted using the board's documented pull-up; no PHOS GPIO connection |
| nINT, if exposed | Unconnected; PHOS polls |
| ADDR, if exposed | Strap per board schematic: low selects 0x5a, high selects 0x5b; do not leave floating |

The provider uses `/dev/i2c-1`, defaults to `0x5a`, also accepts `0x5b`, and
checks HW_ID `0x81`. It never scans or changes address automatically. Separate
worker-owned SMBus handles use the existing kernel I2C bus; no bit-banged bus,
GPIO wake owner or interrupt worker is added. Native transactions stay in the
hardware adapters. CCS811 requires clock stretching; verify sustained combined
operation on the actual Pi/controller, beyond merely finding an address.
See the [manufacturer driver wiring notes](https://github.com/sciosense/CCS811_driver)
and [installation/conditioning procedure](installation.md#optional-ccs811-air-quality-sensor).

### Shared I2C bus

BME280/BMP280, CCS811 and MPU-6050 can share the Raspberry Pi I2C bus if their actual module configuration and addresses are compatible. Keep the 10 kHz bus setting documented for CCS811 when it is present; MPU-6050 works on that shared bus speed.

Before physical acceptance:

- verify the exact I2C addresses of both physical modules;
- verify module voltage requirements and whether each breakout includes regulation/level shifting;
- document the Raspberry Pi pins used for SDA, SCL, power, and ground;
- verify that I2C is enabled on Raspberry Pi OS;
- distinguish the expected BME280 wiring above from the as-built wiring verified on the real hardware.

## Inertial sensor

### GY-521 (MPU-6050)

PHOS supports an optional GY-521 module based on the MPU-6050 through
`robot.hardware.mpu6050.MPU6050Provider`, disabled by default. It publishes
raw acceleration in m/s² and angular velocity in °/s through the IMU service;
it does not publish orientation, gestures or behavior inputs.

The device provides six inertial measurement axes:

- 3-axis accelerometer: X, Y, Z linear acceleration;
- 3-axis gyroscope: X, Y, Z angular velocity / rotation rate.

Wire the verified board to Pi bus 1: **VCC → 3.3 V**, **GND → GND**, **SDA → GPIO2/pin 3**, and **SCL → GPIO3/pin 5**. Use 3.3 V logic and confirm the actual breakout’s regulator and pull-ups before applying power. AD0 low selects `0x68`; AD0 high selects `0x69`. INT, XDA and XCL are not used by PHOS and stay unconnected.

Important distinction: the MPU-6050 measures acceleration and angular velocity. Absolute orientation is not a direct raw sensor output and would require software-side estimation/filtering if needed later.

The adapter wakes the chip, selects ±2 g / ±250 °/s scale, reads the six raw axes and applies only those fixed scale conversions. It intentionally performs no startup bias calibration because that would require PHOS to be perfectly still. Mounting bias and gravity remain in readings. See [installation](installation.md#optional-gy-521--mpu-6050-imu) for I2C verification and setup.

Before physical acceptance:

- verify the exact GY-521 board revision and pin labels;
- verify its supply and logic-level requirements on the actual breakout board;
- verify the configured I2C address (commonly dependent on the AD0 pin state);
- document whether AD0, INT, or other auxiliary pins will be used;
- verify coexistence with BME280/BMP280 and CCS811 on the shared I2C bus;
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

The implemented environmental, air-quality and IMU providers/services are described in [architecture](architecture.md#environmental-sensor-service). They publish read-only state, without behavior integration. Other sensors and light-output abstractions remain deferred.

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

BME280/BMP280 and CCS811 software integration is implemented; wiring, address and real readings await Pi acceptance.

Selected but **not yet integrated in software**:

- GY-521 (MPU-6050);
- WS2812B RGB LED ring.
