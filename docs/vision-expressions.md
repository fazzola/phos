# Vision & expressions

<div class="phos-page-intro" markdown>

<span class="phos-kicker">OBSERVE, THEN RESPOND</span>

PHOS turns camera evidence into a stable semantic observation before behavior
chooses a visual response. It does not mechanically mirror a person.

</div>

<div class="phos-pipeline" markdown>

<span>Camera</span> → <span>Vision</span> → <span>Expression provider</span> → <span>Stable observation</span> → <span>BehaviorEngine</span> → <span>PHOS visual reaction</span>

</div>

PHOS uses the Raspberry Pi Camera to detect, select and track a face. The
selected face position becomes bounded pupil/gaze intent; face tracking and
expression inference have independent cadences.

<div class="phos-callout" markdown>

Expression labels are uncertain observations of a person’s **visible facial
expression**. They are not claims about that person’s internal state, and they
are never treated as PHOS’s own emotion. `BehaviorEngine` chooses PHOS’s subtle
response only after temporal confirmation.

</div>

| Stable observation | PHOS reaction |
| --- | --- |
| Neutral | Calm acknowledgement when enabled after calibration |
| Happy | Warm, friendly visual response |
| Surprised | Temporary alert/open response with cooldown |
| Unknown or rejected negative classes | Preserve/decay toward baseline; no negative mimicry |

Local ONNX is the default selectable expression path. Optional AWS Rekognition
is also available behind the same provider contract; selected crops leave the Pi
only when that mode is enabled, and there is no automatic fallback. Both modes
require physical validation before accuracy claims can be made.

Read the [canonical Vision reference](vision.md) for crop, smoothing, provider,
privacy and calibration details.
