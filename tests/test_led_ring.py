"""WS2812B semantic feedback tests without GPIO or the optional library."""
import sys
import time
from types import SimpleNamespace

from robot.ui import FaceState, LEDRingController, LEDRingSettings, VisualAccent
from robot.config import LED_RING_COLOR_RGB
from robot.ui.led_ring import led_frame, scale_rgb
from robot.hardware.ws2812b import WS2812BProvider
from robot.hardware.ws2812b import LEDRingSocketProvider


def settings(**changes):
    values = dict(enabled=True, led_count=4, gpio_pin=18, brightness=.3, base_color="cyan",
                  follow_visual_state=True, update_rate_hz=30)
    values.update(changes)
    return LEDRingSettings(**values)


def test_semantic_states_map_to_distinct_lightweight_effects_and_preserve_base_color():
    neutral = led_frame(FaceState(), settings(), 0)
    warm = led_frame(FaceState(accent=VisualAccent.WARM, reaction_strength=1), settings(), 0)
    curious = led_frame(FaceState(accent=VisualAccent.CURIOUS, reaction_strength=1), settings(), 0)
    alert = led_frame(FaceState(accent=VisualAccent.ALERT, reaction_strength=1), settings(), 0)
    sleepy = led_frame(FaceState(accent=VisualAccent.SLEEPY, reaction_strength=1), settings(), 0)
    error = led_frame(FaceState(accent=VisualAccent.ERROR, reaction_strength=1), settings(), 0)
    fixed = led_frame(FaceState(accent=VisualAccent.ALERT, reaction_strength=1),
                      settings(follow_visual_state=False, base_color="violet"), 0)

    assert neutral.semantic_state == "neutral" and neutral.effect == "steady"
    assert warm.effect == curious.effect == "pulse"
    assert alert.effect == "alert_pulse" and sleepy.effect == "fade"
    assert error.semantic_state == "error"
    assert len(alert.pixels) == 4 and len(set(alert.pixels)) == 1
    assert fixed.semantic_state == "neutral" and fixed.pixels != alert.pixels


def test_alert_frame_returns_to_configured_baseline_after_transient_state():
    baseline = led_frame(FaceState(), settings(base_color="green"), 1)
    alert = led_frame(FaceState(accent=VisualAccent.ALERT, reaction_strength=1), settings(base_color="green"), 1)
    restored = led_frame(FaceState(), settings(base_color="green"), 2)
    assert alert.pixels != baseline.pixels
    assert restored.semantic_state == "neutral" and restored.pixels == baseline.pixels


def test_named_palette_is_exact_saturated_and_distinct():
    assert LED_RING_COLOR_RGB == {
        "green": (0, 255, 64), "red": (255, 26, 26), "yellow": (255, 212, 0),
        "blue": (0, 123, 255), "violet": (160, 32, 240), "white": (255, 255, 255),
        "cyan": (0, 229, 255), "turquoise": (0, 255, 200), "orange": (255, 122, 0),
        "magenta": (255, 0, 200),
    }
    assert len(set(LED_RING_COLOR_RGB.values())) == len(LED_RING_COLOR_RGB)
    assert LED_RING_COLOR_RGB["white"] == (255, 255, 255)


def test_brightness_scales_each_rgb_channel_without_channel_swapping():
    assert scale_rgb((100, 200, 50), .3) == (30, 60, 15)
    frame = led_frame(FaceState(), settings(base_color="red", brightness=1, follow_visual_state=False), 0)
    assert frame.pixels[0] == LED_RING_COLOR_RGB["red"]


class FakeProvider:
    def __init__(self, fail=False):
        self.started = self.closed = False
        self.frames = []
        self.fail = fail
    def start(self): self.started = True
    def write(self, pixels):
        if self.fail: raise OSError("write failed")
        self.frames.append(tuple(pixels))
    def close(self): self.closed = True


def test_controller_disabled_and_provider_failure_never_raise():
    disabled = LEDRingController(settings(enabled=False, led_count=0), FaceState, lambda _: FakeProvider())
    disabled.start()
    assert disabled.snapshot()["status"] == "disabled"

    failed = FakeProvider(fail=True)
    controller = LEDRingController(settings(), FaceState, lambda _: failed)
    controller.start(); time.sleep(.05); controller.stop()
    assert failed.started and failed.closed
    assert controller.snapshot()["status"] == "unavailable"


def test_controller_initializes_writes_and_live_reloads_visual_settings():
    state = [FaceState()]
    provider = FakeProvider()
    controller = LEDRingController(settings(), lambda: state[0], lambda _: provider)
    controller.start(); time.sleep(.05)
    state[0] = FaceState(accent=VisualAccent.ALERT, reaction_strength=1)
    controller.configure(settings(brightness=.6, base_color="violet"))
    time.sleep(.05); controller.stop()
    assert provider.started and provider.closed and len(provider.frames) >= 2
    assert controller.snapshot()["semantic_state"] == "alert"


def test_ws2812b_provider_is_lazy_and_encodes_rgb_with_grb_transport_without_hardware(monkeypatch):
    calls = []
    class Strip:
        def __init__(self, count, pin, brightness, strip_type): calls.append(("init", count, pin, brightness, strip_type))
        def begin(self): calls.append(("begin",))
        def setPixelColor(self, index, color): calls.append(("pixel", index, color))
        def show(self): calls.append(("show",))
    monkeypatch.setitem(sys.modules, "rpi_ws281x", SimpleNamespace(
        PixelStrip=Strip, Color=lambda red, green, blue: (red << 16) | (green << 8) | blue,
        ws=SimpleNamespace(WS2811_STRIP_GRB="GRB")))
    provider = WS2812BProvider(led_count=2, gpio_pin=18)
    provider.start()
    provider.write(((1, 2, 3), (4, 5, 6)))
    provider.close()
    assert calls == [("init", 2, 18, 255, "GRB"), ("begin",), ("pixel", 0, 0x010203),
                     ("pixel", 1, 0x040506), ("show",), ("pixel", 0, 0), ("pixel", 1, 0), ("show",)]


def test_unprivileged_socket_provider_sends_only_bounded_pixel_frames(tmp_path, monkeypatch):
    import json
    path = tmp_path / "led.sock"; path.touch()
    sent = []
    class Socket:
        def sendto(self, payload, target): sent.append((payload, target))
        def close(self): pass
    monkeypatch.setattr("robot.hardware.ws2812b.socket.socket", lambda *_: Socket())
    provider = LEDRingSocketProvider(led_count=2, socket_path=str(path))
    provider.start()
    provider.write(((1, 2, 3), (4, 5, 6)))
    assert json.loads(sent[0][0]) == {"pixels": [[1, 2, 3], [4, 5, 6]]}
    provider.close()
