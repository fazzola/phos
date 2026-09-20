# PHOS Core / Behavior Instructions

Applies to lifecycle, state, events, orchestration and `BehaviorEngine`.

## Core responsibilities
- Keep robot-state transitions explicit and testable.
- Keep runtime/orchestration thin; subsystem-specific implementation belongs in its subsystem.
- Use events where they materially reduce coupling, not as a replacement for every normal call.
- Preserve clean startup/shutdown and cancellation behavior.
- Do not let AI/business logic directly access GPIO or vendor-specific hardware APIs.

## Behavior responsibilities
`BehaviorEngine` converts robot state plus stable observations into PHOS behavior/visual intent.

- PHOS has its own personality; do not simply mirror a person's facial expression.
- Preserve existing/equivalent visual modes such as `NEUTRAL`, `HAPPY`, `CURIOUS`, `SURPRISED`, `SLEEPY` and any established error-state representation.
- Negative/sad/angry-like visual observations should normally produce attentive/neutral/soft PHOS behavior, not an angry or sad mirror reaction.
- Robot state has priority over Vision. In particular, `SLEEPING` must produce sleepy behavior regardless of Vision.
- Keep short-lived reactions conceptually separate from slower persistent state/mood.
- Apply temporal decay/smoothing so reactions do not oscillate frame by frame.
- Face position may influence a normalized attention/gaze target; clamp and smooth it.
- Blink scheduling/randomness should remain independently testable; prefer injectable time/randomness when changing this code.
- `BehaviorEngine` outputs `FaceState`; it does not draw pixels.
- UI-specific geometry remains in the UI layer.
