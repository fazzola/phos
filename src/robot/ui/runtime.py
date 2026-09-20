"""Fixed-rate UI runtime, independent from behavior and Vision timing."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Optional

from robot.core.behaviors import Behavior

from .display import EyeDisplay
from .eyes import EyeRenderer
from .state import FaceState


class EyeRenderLoop(Behavior):
    """Render the latest FaceState at a display rate independent of Vision."""

    name = "eye-render-loop"

    def __init__(
        self,
        renderer: EyeRenderer,
        display: EyeDisplay,
        state_supplier: Callable[[], FaceState],
        *,
        fps: int = 30,
        fullscreen: bool = True,
    ) -> None:
        if fps <= 0:
            raise ValueError("fps must be positive.")
        self._renderer = renderer
        self._display = display
        self._state_supplier = state_supplier
        self._frame_interval = 1.0 / fps
        self._fullscreen = fullscreen
        self._task: Optional[asyncio.Task[None]] = None

    async def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("Eye render loop is already running.")
        try:
            initial = self._renderer.render(self._state_supplier(), timestamp=time.monotonic())
            self._display.open(initial.width, initial.height, fullscreen=self._fullscreen)
            self._display.draw(initial)
            self._task = asyncio.create_task(self._run(), name="eye-render-loop")
        except Exception:
            try:
                self._display.close()
            except Exception:
                pass
            raise

    async def stop(self) -> None:
        failure: Optional[Exception] = None
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception as error:
                failure = error
            self._task = None
        try:
            self._display.close()
        except Exception as error:
            if failure is None:
                failure = error
        if failure is not None:
            raise failure

    async def wait(self) -> None:
        """Wait for the render task; used by the application supervisor."""
        if self._task is None:
            raise RuntimeError("Eye render loop is not running.")
        await asyncio.shield(self._task)

    async def _run(self) -> None:
        while True:
            started_at = time.monotonic()
            frame = self._renderer.render(self._state_supplier(), timestamp=started_at)
            self._display.draw(frame)
            self._display.poll_keys()
            await asyncio.sleep(max(0.0, self._frame_interval - (time.monotonic() - started_at)))
