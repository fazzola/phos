"""Start the PHOS robot runtime.

The default renderer opens the face fullscreen on the Pi's HDMI desktop.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

# Allow direct execution from a source checkout with
# ``python3 src/robot/main.py`` without a package installation.
SOURCE_DIRECTORY = Path(__file__).resolve().parent.parent
if str(SOURCE_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIRECTORY))

from robot.runtime import PhosRuntime, build_runtime

logger = logging.getLogger(__name__)


def build_application() -> PhosRuntime:
    """Compose the single PHOS application/runtime coordinator."""
    return build_runtime()


def _install_shutdown_handlers(loop: asyncio.AbstractEventLoop, stop_event: asyncio.Event) -> None:
    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(shutdown_signal, stop_event.set)
        except NotImplementedError:
            # Signal handlers are unavailable on some event-loop platforms.
            pass


async def async_main() -> None:
    stop_event = asyncio.Event()
    _install_shutdown_handlers(asyncio.get_running_loop(), stop_event)
    await build_application().run(stop_event)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
