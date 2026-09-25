"""Display adapters for rendered PHOS eye geometry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import logging
import time
from typing import Any, Deque, List, Optional

from .eyes import EyeFrame, EyeGeometry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CameraPreviewView:
    """UI-neutral, in-memory image and already-produced Vision diagnostics."""
    frame: Any
    face_box: Optional[tuple[int, int, int, int]] = None
    expression: Optional[str] = None
    confidence: Optional[float] = None
    semantic_expression: Optional[str] = None


@dataclass(frozen=True)
class CameraPreviewSettings:
    enabled: bool = False
    position: str = "bottom_right"
    scale: float = .25
    max_fps: int = 5
    show_face_box: bool = True
    show_expression: bool = True
    show_confidence: bool = True


class EyeDisplay(ABC):
    """Display-driver boundary for precomputed eye geometry."""

    @abstractmethod
    def open(self, width: int, height: int, *, fullscreen: bool) -> None:
        raise NotImplementedError

    @abstractmethod
    def draw(self, frame: EyeFrame, preview: Optional[CameraPreviewView] = None,
             preview_settings: Optional[CameraPreviewSettings] = None) -> None:
        raise NotImplementedError

    @abstractmethod
    def poll_keys(self) -> List[str]:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError


class MemoryEyeDisplay(EyeDisplay):
    """Headless display adapter used by tests."""

    def __init__(self) -> None:
        self.frames: List[EyeFrame] = []

    def open(self, width: int, height: int, *, fullscreen: bool) -> None:
        return None

    def draw(self, frame: EyeFrame, preview: Optional[CameraPreviewView] = None,
             preview_settings: Optional[CameraPreviewSettings] = None) -> None:
        self.frames.append(frame)

    def poll_keys(self) -> List[str]:
        return []

    def close(self) -> None:
        return None


class TkEyeDisplay(EyeDisplay):
    """Lightweight fullscreen Tkinter display for the HDMI desktop."""

    def __init__(self) -> None:
        self._root = None
        self._canvas = None
        self._tk = None
        self._keys: Deque[str] = deque()
        self._preview_executor = None
        self._preview_future: Optional[Future] = None
        self._preview_photo = None
        self._preview_next_at = 0.0
        self._preview_failed = False
        self._preview_discard_pending = False

    def open(self, width: int, height: int, *, fullscreen: bool) -> None:
        if self._root is not None:
            return
        try:
            import tkinter as tk
        except ImportError as error:
            raise RuntimeError("Tkinter is required to display PHOS eyes.") from error
        try:
            root = tk.Tk()
        except tk.TclError as error:
            raise RuntimeError("Could not open the PHOS HDMI display from this session.") from error
        root.title("PHOS")
        root.geometry(f"{width}x{height}+0+0")
        root.attributes("-fullscreen", fullscreen)
        root.bind("<Escape>", lambda _event: root.attributes("-fullscreen", False))
        root.bind("<Key>", lambda event: self._keys.append(event.keysym))
        canvas = tk.Canvas(root, highlightthickness=0, borderwidth=0)
        canvas.pack(fill=tk.BOTH, expand=True)
        self._root = root
        self._canvas = canvas
        self._tk = tk
        self._preview_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="phos-preview")

    def draw(self, frame: EyeFrame, preview: Optional[CameraPreviewView] = None,
             preview_settings: Optional[CameraPreviewSettings] = None) -> None:
        if self._root is None or self._canvas is None:
            raise RuntimeError("Display has not been opened.")
        self._canvas.delete("all")
        self._canvas.configure(background=frame.background)
        for eye in frame.eyes:
            self._draw_eye(eye, frame)
        settings = preview_settings or CameraPreviewSettings()
        if preview is not None and settings.enabled:
            self._draw_preview(preview, settings, frame.width, frame.height)
        else:
            self._preview_photo = None
            if self._preview_future is not None:
                # A running encoder cannot be cancelled. Keep its slot occupied
                # until it finishes, even across rapid preview off/on reloads.
                self._preview_discard_pending = True
                if self._preview_future.cancel() or self._preview_future.done():
                    self._preview_future = None

    def poll_keys(self) -> List[str]:
        if self._root is not None:
            self._root.update_idletasks()
            self._root.update()
        keys = list(self._keys)
        self._keys.clear()
        return keys

    def close(self) -> None:
        if self._root is not None:
            try:
                self._root.destroy()
            except self._tk.TclError:
                pass
        self._root = None
        self._canvas = None
        self._tk = None
        self._preview_photo = None
        if self._preview_executor is not None:
            self._preview_executor.shutdown(wait=False, cancel_futures=True)
            self._preview_executor = None
        self._preview_future = None

    def _draw_eye(self, eye: EyeGeometry, frame: EyeFrame) -> None:
        if eye.closed:
            self._canvas.create_arc(
                eye.center_x - eye.radius_x,
                eye.center_y - 18,
                eye.center_x + eye.radius_x,
                eye.center_y + 24,
                start=200,
                extent=140,
                style=self._tk.ARC,
                outline=frame.eye_color,
                width=12,
            )
            return
        # A compact stack of Canvas primitives gives the eye body and iris
        # depth without raster assets, per-frame filters, or external graphics.
        self._canvas.create_oval(
            eye.center_x - eye.radius_x,
            eye.center_y - eye.radius_y + 7,
            eye.center_x + eye.radius_x,
            eye.center_y + eye.radius_y + 7,
            fill="#071522",
            outline="",
        )
        self._canvas.create_oval(
            eye.center_x - eye.radius_x,
            eye.center_y - eye.radius_y,
            eye.center_x + eye.radius_x,
            eye.center_y + eye.radius_y,
            fill="#8FA8B8",
            outline="#526C80",
            width=3,
        )
        inset = 5
        self._canvas.create_oval(
            eye.center_x - eye.radius_x + inset,
            eye.center_y - eye.radius_y + inset,
            eye.center_x + eye.radius_x - inset,
            eye.center_y + eye.radius_y - inset,
            fill=frame.eye_color,
            outline="",
        )
        self._canvas.create_oval(
            eye.pupil_x - eye.iris_radius,
            eye.pupil_y - eye.iris_radius,
            eye.pupil_x + eye.iris_radius,
            eye.pupil_y + eye.iris_radius,
            fill="#123246",
            outline="",
        )
        iris_inset = max(1.5, eye.iris_radius * 0.10)
        self._canvas.create_oval(
            eye.pupil_x - eye.iris_radius + iris_inset,
            eye.pupil_y - eye.iris_radius + iris_inset,
            eye.pupil_x + eye.iris_radius - iris_inset,
            eye.pupil_y + eye.iris_radius - iris_inset,
            fill=frame.iris_color,
            outline="",
        )
        # The dark pupil is distinct from the colored iris; small glints sell
        # a glassy surface without a blur/filter pass.
        self._canvas.create_oval(
            eye.pupil_x - eye.pupil_radius,
            eye.pupil_y - eye.pupil_radius,
            eye.pupil_x + eye.pupil_radius,
            eye.pupil_y + eye.pupil_radius,
            fill=frame.pupil_color,
            outline="#071522",
            width=2,
        )
        highlight = max(2.0, eye.pupil_radius * 0.24)
        self._canvas.create_oval(
            eye.pupil_x - eye.iris_radius * 0.33 - highlight,
            eye.pupil_y - eye.iris_radius * 0.33 - highlight,
            eye.pupil_x - eye.iris_radius * 0.33 + highlight,
            eye.pupil_y - eye.iris_radius * 0.33 + highlight,
            fill="#FFFFFF",
            outline="",
        )
        glint = max(1.2, highlight * 0.42)
        self._canvas.create_oval(
            eye.pupil_x + eye.iris_radius * 0.30 - glint,
            eye.pupil_y + eye.iris_radius * 0.28 - glint,
            eye.pupil_x + eye.iris_radius * 0.30 + glint,
            eye.pupil_y + eye.iris_radius * 0.28 + glint,
            fill="#D9FBFF",
            outline="",
        )

    def _draw_preview(self, preview, settings, display_width, display_height):
        now = time.monotonic()
        if self._preview_future is not None and self._preview_future.done():
            try:
                _width, _height, encoded = self._preview_future.result()
                if not self._preview_discard_pending:
                    self._preview_photo = self._tk.PhotoImage(data=encoded, format="PPM")
                    self._preview_failed = False
            except Exception:
                self._preview_photo = None
                if not self._preview_failed:
                    logger.exception("Could not render camera preview")
                self._preview_failed = True
            self._preview_future = None
        if self._preview_future is None and now >= self._preview_next_at:
            shape = getattr(preview.frame, "shape", ())
            if len(shape) >= 2:
                target_width = max(80, int(display_width * settings.scale))
                self._preview_future = self._preview_executor.submit(_encode_preview_ppm, preview.frame, target_width)
                self._preview_discard_pending = False
                self._preview_next_at = now + 1.0 / settings.max_fps
        if self._preview_photo is None:
            return
        image_width, image_height = self._preview_photo.width(), self._preview_photo.height()
        margin = 16
        x = margin if "left" in settings.position else display_width - image_width - margin
        y = margin if settings.position.startswith("top") else display_height - image_height - margin
        self._canvas.create_rectangle(x - 3, y - 3, x + image_width + 3, y + image_height + 3,
                                      fill="#06111b", outline="#61d8e8", width=2)
        self._canvas.create_image(x, y, image=self._preview_photo, anchor="nw")
        shape = getattr(preview.frame, "shape", ())
        if settings.show_face_box and preview.face_box and len(shape) >= 2:
            sx, sy = image_width / shape[1], image_height / shape[0]
            fx, fy, fw, fh = preview.face_box
            self._canvas.create_rectangle(x + fx * sx, y + fy * sy,
                x + (fx + fw) * sx, y + (fy + fh) * sy, outline="#ffe66d", width=2)
        if settings.show_expression:
            labels = []
            if preview.expression:
                label = preview.expression
                if settings.show_confidence and preview.confidence is not None:
                    label += f" {preview.confidence:.0%}"
                labels.append(f"Raw: {label}")
            if preview.semantic_expression:
                labels.append(f"PHOS: {preview.semantic_expression}")
            for index, label in enumerate(labels):
                self._canvas.create_text(x + 5, y + image_height - 5 - index * 17, text=label,
                    anchor="sw", fill="white", font=("TkDefaultFont", 9, "bold"))


def _encode_preview_ppm(frame, target_width):
    """Resize and encode off the Tk/display thread; only one job can be pending."""
    import cv2
    height, width = frame.shape[:2]
    target_height = max(1, round(height * target_width / width))
    small = cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_AREA)
    # Preview arrays follow the existing OpenCV BGR contract; PPM requires RGB.
    small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
    header = f"P6 {target_width} {target_height} 255\n".encode("ascii")
    # Tk's PPM reader requires raw binary data, not base64 text.
    return target_width, target_height, header + small.tobytes()
