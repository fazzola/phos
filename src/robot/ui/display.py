"""Display adapters for rendered PHOS eye geometry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from typing import Deque, List

from .eyes import EyeFrame, EyeGeometry


class EyeDisplay(ABC):
    """Display-driver boundary for precomputed eye geometry."""

    @abstractmethod
    def open(self, width: int, height: int, *, fullscreen: bool) -> None:
        raise NotImplementedError

    @abstractmethod
    def draw(self, frame: EyeFrame) -> None:
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

    def draw(self, frame: EyeFrame) -> None:
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

    def draw(self, frame: EyeFrame) -> None:
        if self._root is None or self._canvas is None:
            raise RuntimeError("Display has not been opened.")
        self._canvas.delete("all")
        self._canvas.configure(background=frame.background)
        for eye in frame.eyes:
            self._draw_eye(eye, frame)

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
