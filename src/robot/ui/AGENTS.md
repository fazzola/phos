# PHOS UI / Eyes Instructions

The UI renders PHOS visual state. It must not decide robot behavior.

## Boundary
`BehaviorEngine → FaceState → EyeRenderer → display`

- `EyeRenderer` consumes `FaceState` for semantic visual intent and a small,
  validated appearance configuration (currently the named iris theme).
- Appearance reloads must pass through the lifecycle/application service and
  the render-loop update queue; web adapters must never mutate renderer state.
- `EyeRenderer` must not depend on Vision, OpenCV, Picamera2, expression-model labels, LLM, TTS or Home Assistant. The display adapter may compose a separate optional diagnostic picture-in-picture from a UI-neutral latest-frame/diagnostic value supplied by the application runtime; it must not access Vision or camera providers itself.
- Camera preview composition must use bounded/drop-old work and remain subordinate to eye rendering. Preview settings arrive through the canonical configuration lifecycle service.
- The renderer decides HOW a state looks; `BehaviorEngine` decides WHICH state PHOS has.

## Current visual milestone
The first runnable visual milestone targets an 800×600 display with two expressive eyes and no required mouth.
Support the existing/equivalent modes: neutral, happy, curious, surprised and sleepy.
Support smooth interpolation, bounded/subtle pupil movement and a natural blink progression.
Display animation must be independent from Vision inference frequency.
Named iris appearance settings may be applied live without restarting Core,
Vision, BehaviorEngine or providers. Unsafe display geometry/backend settings
remain restart-required.

## Performance and testing
- Prefer a lightweight rendering backend suitable for Raspberry Pi 3; do not introduce a heavy GUI framework without a documented reason.
- Avoid expensive per-frame allocations and blocking work in the render loop.
- Separate pure animation/geometry from drawing where practical so it can be unit tested without physical display hardware.
- Maintain a development/demo entry point that can exercise eye states without camera, Vision or AI when the repository architecture permits it.
