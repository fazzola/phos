"""Provider-neutral semantic LED ring controller."""
from __future__ import annotations

from dataclasses import dataclass
import logging
import math
from threading import Event, Lock, Thread
import time
from typing import Callable, Optional, Tuple

from robot.hardware.ws2812b import LEDRingProvider, RGB

from .state import FaceState, VisualAccent

logger = logging.getLogger(__name__)

_COLORS = {
    "cyan": (40, 206, 235), "blue": (73, 133, 255), "green": (65, 205, 125),
    "turquoise": (35, 200, 175), "amber": (244, 171, 61), "violet": (166, 112, 245),
    "white": (218, 236, 246),
}
_ACCENT_COLORS = {
    VisualAccent.WARM: (48, 226, 178), VisualAccent.CURIOUS: (79, 195, 248),
    VisualAccent.ALERT: (255, 191, 72), VisualAccent.SLEEPY: (173, 145, 248),
    VisualAccent.ERROR: (255, 93, 111),
}


@dataclass(frozen=True)
class LEDRingSettings:
    enabled: bool
    led_count: int
    gpio_pin: int
    brightness: float
    base_color: str
    follow_visual_state: bool
    update_rate_hz: float


@dataclass(frozen=True)
class LEDRingFrame:
    semantic_state: str
    effect: str
    pixels: Tuple[RGB, ...]


def led_frame(state: FaceState, settings: LEDRingSettings, now: float) -> LEDRingFrame:
    """Map UI-neutral semantic intent to a small, uniform LED effect."""
    state = state.normalized()
    accent = state.accent if settings.follow_visual_state else VisualAccent.NEUTRAL
    color = _ACCENT_COLORS.get(accent, _COLORS[settings.base_color])
    effect, multiplier = "steady", 1.0
    if accent in {VisualAccent.WARM, VisualAccent.CURIOUS}:
        effect, multiplier = "pulse", .88 + .12 * (1 + math.sin(now * (1.5 if accent is VisualAccent.WARM else 1.0))) / 2
    elif accent is VisualAccent.ALERT:
        effect, multiplier = "alert_pulse", .65 + .35 * max(state.reaction_strength, .5) * (1 + math.sin(now * 12)) / 2
    elif accent is VisualAccent.SLEEPY:
        effect, multiplier = "fade", .25 + .10 * (1 + math.sin(now * .7)) / 2
    elif accent is VisualAccent.ERROR:
        effect, multiplier = "steady", .85
    scale = max(0.0, min(1.0, settings.brightness * multiplier))
    pixel = tuple(round(channel * scale) for channel in color)
    return LEDRingFrame(accent.value, effect, (pixel,) * settings.led_count)


class LEDRingController:
    """Dedicated low-rate worker; provider failures never affect PHOS rendering."""

    def __init__(self, settings: LEDRingSettings, state_supplier: Callable[[], FaceState],
                 provider_factory: Callable[[LEDRingSettings], LEDRingProvider], *, clock=time.monotonic) -> None:
        self._settings, self._state_supplier, self._factory, self._clock = settings, state_supplier, provider_factory, clock
        self._lock, self._stop = Lock(), Event()
        self._thread: Optional[Thread] = None
        self._status = {"status": "disabled" if not settings.enabled else "starting", "semantic_state": None,
                        "effect": None, "error": None}

    def start(self) -> None:
        with self._lock:
            if not self._settings.enabled or self._thread is not None:
                return
            self._stop.clear()
            self._status.update(status="starting", error=None)
            self._thread = Thread(target=self._run, name="phos-led-ring", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            self._thread = None
            self._stop.set()
        if thread is not None:
            thread.join(timeout=2)
        with self._lock:
            if not self._settings.enabled:
                self._status.update(status="disabled", semantic_state=None, effect=None, error=None)

    def configure(self, settings: LEDRingSettings) -> None:
        """Apply visual settings live; lifecycle classifies pin/count as restart-only."""
        with self._lock:
            previous_enabled = self._settings.enabled
            self._settings = settings
        if previous_enabled != settings.enabled:
            self.stop()
            if settings.enabled:
                self.start()

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._status)

    def _run(self) -> None:
        provider = None
        last_warning = float("-inf")
        try:
            with self._lock:
                settings = self._settings
            provider = self._factory(settings)
            provider.start()
            with self._lock:
                self._status.update(status="available", error=None)
            while not self._stop.is_set():
                with self._lock:
                    settings = self._settings
                frame = led_frame(self._state_supplier(), settings, self._clock())
                try:
                    provider.write(frame.pixels)
                    with self._lock:
                        self._status.update(status="available", semantic_state=frame.semantic_state,
                                            effect=frame.effect, error=None)
                except Exception as error:
                    now = self._clock()
                    with self._lock:
                        self._status.update(status="unavailable", error=type(error).__name__)
                    if now - last_warning >= 60:
                        logger.warning("LED ring unavailable (%s: %s); continuing without LED output", type(error).__name__, error)
                        last_warning = now
                self._stop.wait(1.0 / settings.update_rate_hz)
        except Exception as error:
            with self._lock:
                self._status.update(status="unavailable", error=type(error).__name__)
            logger.warning("LED ring unavailable (%s: %s); continuing without LED output", type(error).__name__, error)
        finally:
            if provider is not None:
                try:
                    provider.close()
                except Exception:
                    logger.debug("LED ring cleanup failed", exc_info=True)
