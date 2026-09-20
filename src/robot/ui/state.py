"""Provider-neutral state consumed by the PHOS eye renderer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


class FaceExpression(str, Enum):
    NEUTRAL = "neutral"
    HAPPY = "happy"
    CURIOUS = "curious"
    SURPRISED = "surprised"
    SLEEPY = "sleepy"
    WORRIED = "worried"


class VisualAccent(str, Enum):
    """Provider-neutral color intent for PHOS's visual reaction."""

    NEUTRAL = "neutral"
    WARM = "warm"
    CURIOUS = "curious"
    ALERT = "alert"
    SLEEPY = "sleepy"
    ERROR = "error"


class BlinkPhase(str, Enum):
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"
    OPENING = "opening"


_HEX_COLOR = re.compile(r"#[0-9A-Fa-f]{6}")


@dataclass(frozen=True)
class FaceState:
    """The complete visual intent for one renderer frame."""

    background: str = "#10243A"
    eye_open: float = 1.0
    squint: float = 0.0
    pupil_x: float = 0.0
    pupil_y: float = 0.0
    reaction_strength: float = 0.0
    expression: FaceExpression = FaceExpression.NEUTRAL
    accent: VisualAccent = VisualAccent.NEUTRAL
    blink_phase: BlinkPhase = BlinkPhase.OPEN
    blink_progress: float = 0.0

    def normalized(self) -> "FaceState":
        expression = self.expression if isinstance(self.expression, FaceExpression) else FaceExpression.NEUTRAL
        accent = self.accent if isinstance(self.accent, VisualAccent) else VisualAccent.NEUTRAL
        blink_phase = self.blink_phase if isinstance(self.blink_phase, BlinkPhase) else BlinkPhase.OPEN
        background = self.background if isinstance(self.background, str) else "#10243A"
        return FaceState(
            background=background if _HEX_COLOR.fullmatch(background) else "#10243A",
            eye_open=_clamp(self.eye_open, 0.0, 1.25),
            squint=_clamp(self.squint, 0.0, 1.0),
            pupil_x=_clamp(self.pupil_x, -1.0, 1.0),
            pupil_y=_clamp(self.pupil_y, -1.0, 1.0),
            reaction_strength=_clamp(self.reaction_strength, 0.0, 1.0),
            expression=expression,
            accent=accent,
            blink_phase=blink_phase,
            blink_progress=_clamp(self.blink_progress, 0.0, 1.0),
        )


def _clamp(value: float, lower: float, upper: float) -> float:
    try:
        return max(lower, min(float(value), upper))
    except (TypeError, ValueError):
        return lower
