"""Start the PHOS robot runtime.

The default renderer opens the face fullscreen on the Pi's HDMI desktop.
"""

from __future__ import annotations

import asyncio
import argparse
import logging
import math
import signal
import sys
from pathlib import Path

# Allow direct execution from a source checkout with
# ``python3 src/robot/main.py`` without a package installation.
SOURCE_DIRECTORY = Path(__file__).resolve().parent.parent
if str(SOURCE_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIRECTORY))

from robot.runtime import PhosRuntime, RuntimeConfig, build_runtime

logger = logging.getLogger(__name__)


def build_application(*, config: RuntimeConfig = RuntimeConfig()) -> PhosRuntime:
    """Compose the single PHOS application/runtime coordinator."""
    return build_runtime(config=config)


def _install_shutdown_handlers(loop: asyncio.AbstractEventLoop, stop_event: asyncio.Event) -> None:
    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(shutdown_signal, stop_event.set)
        except NotImplementedError:
            # Signal handlers are unavailable on some event-loop platforms.
            pass


async def async_main(*, config: RuntimeConfig = RuntimeConfig()) -> None:
    stop_event = asyncio.Event()
    _install_shutdown_handlers(asyncio.get_running_loop(), stop_event)
    await build_application(config=config).run(stop_event)


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the PHOS robot runtime.")
    parser.add_argument(
        "--face-tracking",
        action="store_true",
        help="enable Raspberry Pi Camera face tracking without expression classification",
    )
    parser.add_argument(
        "--expression-model",
        type=Path,
        help="path to an ONNX visible-expression model; also enables camera Vision",
    )
    parser.add_argument(
        "--expression-labels",
        help="comma-separated output labels, in the exact model-output order",
    )
    parser.add_argument(
        "--expression-input-size",
        default="64x64",
        help="ONNX model input size as WIDTHxHEIGHT (default: 64x64)",
    )
    parser.add_argument(
        "--expression-scale",
        type=float,
        default=1.0 / 255.0,
        help="OpenCV DNN image scale for the expression model (default: 1/255)",
    )
    parser.add_argument(
        "--expression-mean",
        default="0,0,0",
        help="three OpenCV DNN image-mean values (default: 0,0,0)",
    )
    parser.add_argument(
        "--expression-no-swap-rb",
        action="store_true",
        help="do not swap BGR camera channels to RGB before expression inference",
    )
    parser.add_argument(
        "--expression-grayscale",
        action="store_true",
        help="convert RGB face crops to one-channel grayscale before expression inference",
    )
    parser.add_argument(
        "--expression-debug",
        action="store_true",
        help="log in-memory face-crop, blob, output, and smoothing diagnostics; no images are saved",
    )
    parser.add_argument(
        "--expression-crop-margin", type=float, default=0.10,
        help="square face crop margin per side, as a face-size fraction (0 to 0.5; default: 0.10)",
    )
    arguments = parser.parse_args()
    if not math.isfinite(arguments.expression_crop_margin) or not 0 <= arguments.expression_crop_margin <= 0.5:
        parser.error("--expression-crop-margin must be between zero and 0.5")
    if (arguments.expression_model is None) != (arguments.expression_labels is None):
        parser.error("--expression-model and --expression-labels must be provided together")
    try:
        width, height = (int(value) for value in arguments.expression_input_size.lower().split("x", 1))
        input_size = (width, height)
    except ValueError:
        parser.error("--expression-input-size must be WIDTHxHEIGHT")
    try:
        mean = tuple(float(value) for value in arguments.expression_mean.split(","))
    except ValueError:
        parser.error("--expression-mean must be three comma-separated numbers")
    if len(mean) != 3:
        parser.error("--expression-mean must be three comma-separated numbers")
    labels = tuple(label.strip() for label in (arguments.expression_labels or "").split(",") if label.strip())
    if arguments.expression_model is not None and not labels:
        parser.error("--expression-labels must contain at least one label")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("phos.log", encoding="utf-8"),
        ],
    )
    asyncio.run(
        async_main(
            config=RuntimeConfig(
                face_tracking_enabled=arguments.face_tracking,
                expression_model_path=arguments.expression_model,
                expression_labels=labels,
                expression_input_size=input_size,
                expression_scale=arguments.expression_scale,
                expression_mean=mean,
                expression_swap_rb=not arguments.expression_no_swap_rb,
                expression_grayscale=arguments.expression_grayscale,
                expression_diagnostics=arguments.expression_debug,
                expression_crop_margin=arguments.expression_crop_margin,
            )
        )
    )


if __name__ == "__main__":
    main()
