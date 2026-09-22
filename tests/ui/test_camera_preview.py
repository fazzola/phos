"""Preview image transport and error handling without camera/display hardware."""

from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import Mock

from robot.ui.display import (
    CameraPreviewSettings, CameraPreviewView, TkEyeDisplay, _encode_preview_ppm,
)


def test_preview_passes_binary_ppm_to_tk_and_draws_image(monkeypatch):
    pixels = b"\x00\x80\xff" * 2
    small = SimpleNamespace(tobytes=lambda: pixels)
    resize = Mock(return_value=small)
    monkeypatch.setitem(__import__("sys").modules, "cv2",
                        SimpleNamespace(resize=resize, INTER_AREA=3))
    frame = SimpleNamespace(shape=(2, 4, 3))
    encoded = _encode_preview_ppm(frame, 2)
    assert encoded == (2, 1, b"P6 2 1 255\n" + pixels)
    resize.assert_called_once_with(frame, (2, 1), interpolation=3)

    photo = SimpleNamespace(width=lambda: 2, height=lambda: 1)
    display = TkEyeDisplay()
    display._tk = SimpleNamespace(PhotoImage=Mock(return_value=photo))
    display._canvas = Mock()
    display._preview_next_at = float("inf")
    display._preview_future = Future()
    display._preview_future.set_result(encoded)
    display._draw_preview(CameraPreviewView(frame), CameraPreviewSettings(enabled=True), 800, 600)

    display._tk.PhotoImage.assert_called_once_with(data=encoded[2], format="PPM")
    display._canvas.create_image.assert_called_once_with(782, 583, image=photo, anchor="nw")


def test_preview_failure_is_logged_once_until_recovery(caplog):
    display = TkEyeDisplay()
    display._preview_next_at = float("inf")
    preview = CameraPreviewView(SimpleNamespace(shape=(2, 4, 3)))
    settings = CameraPreviewSettings(enabled=True)
    for _ in range(2):
        display._preview_future = Future()
        display._preview_future.set_exception(ValueError("invalid preview data"))
        display._draw_preview(preview, settings, 800, 600)
    assert caplog.text.count("Could not render camera preview") == 1
    assert "invalid preview data" in caplog.text
    assert display._preview_photo is None
    assert display._preview_future is None

    display._tk = SimpleNamespace(PhotoImage=Mock(return_value=SimpleNamespace(width=lambda: 2, height=lambda: 1)))
    display._canvas = Mock()
    display._preview_future = Future()
    display._preview_future.set_result((2, 1, b"P6 2 1 255\n" + b"\x00" * 6))
    display._draw_preview(preview, settings, 800, 600)
    assert not display._preview_failed
