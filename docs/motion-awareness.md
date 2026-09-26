# Motion awareness

<div class="phos-page-intro" markdown>

<span class="phos-kicker">MOTION AS SEMANTICS</span>

Motion is interpreted as a confirmed event, not treated as a direct renderer or
GPIO command.

</div>

<div class="phos-pipeline" markdown>

<span>MPU-6050</span> → <span>MotionInterpreter</span> → <span>MotionState / MotionEvent</span> → <span>BehaviorEngine</span> → <span>Eyes / LED ring</span>

</div>

The optional GY-521/MPU-6050 service reads acceleration and angular velocity;
it does not send raw values to the renderer or GPIO. `MotionInterpreter` turns
fresh samples into confirmed semantic states: **STILL**, **MOVING**,
**TILT_LEFT**, **TILT_RIGHT**, **TILT_FORWARD**, **TILT_BACK**, **SHAKE** and
**IMPACT**.

Directional tilt produces directional pupil intent and eye asymmetry. The
optional WS2812B ring can show progressive directional fill animations. Shake
and impact create short alert intent. These are temporary overrides: they do not
rewrite the configured base source, and the currently resolved persistent visual
state returns after the effect expires.

<div class="phos-callout" markdown>

The adapter and interpretation are implemented, but board wiring, mounting axes
and target-Pi behavior still need release acceptance. Details belong in the
[canonical hardware guide](hardware.md#gy-521-mpu-6050) and
[architecture reference](architecture.md#motion-interpretation-extension).

</div>
