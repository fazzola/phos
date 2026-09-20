"""Start the PHOS robot runtime.

The default renderer opens the face fullscreen on the Pi's HDMI desktop.
"""

from __future__ import annotations

import asyncio
import argparse
from dataclasses import replace
import logging
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
    parser = argparse.ArgumentParser(description="Start the PHOS robot runtime.",
                                     argument_default=argparse.SUPPRESS)
    parser.add_argument("--config", type=Path, help="JSON file containing RuntimeConfig settings")
    parser.add_argument("--expression-provider", choices=("local", "aws"))
    parser.add_argument("--aws-region", help="override cloud_expression.region")
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
        help="ONNX model input size as WIDTHxHEIGHT (default: 64x64)",
    )
    parser.add_argument(
        "--expression-scale",
        type=float,
        help="OpenCV DNN image scale for the expression model (default: 1/255)",
    )
    parser.add_argument(
        "--expression-mean",
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
        "--expression-crop-margin", type=float,
        help="square face crop margin per side, as a face-size fraction (0 to 0.5; default: 0.10)",
    )
    # Only explicitly supplied arguments override the file/dataclass defaults.
    arguments = vars(parser.parse_args())
    try:
        config_path = arguments.pop("config", None)
        config = RuntimeConfig.from_file(config_path) if config_path else RuntimeConfig()
        aliases = {"face_tracking": "face_tracking_enabled", "expression_model": "expression_model_path",
                   "expression_debug": "expression_diagnostics"}
        overrides = {aliases.get(name, name): value for name, value in arguments.items()}
        if "expression_labels" in overrides:
            overrides["expression_labels"] = tuple(v.strip() for v in overrides["expression_labels"].split(",") if v.strip())
        if "expression_input_size" in overrides:
            overrides["expression_input_size"] = tuple(int(v) for v in overrides["expression_input_size"].lower().split("x"))
            if len(overrides["expression_input_size"]) != 2 or min(overrides["expression_input_size"]) <= 0:
                raise ValueError("--expression-input-size must be positive WIDTHxHEIGHT")
        if "expression_mean" in overrides:
            overrides["expression_mean"] = tuple(float(v) for v in overrides["expression_mean"].split(","))
        if "expression_no_swap_rb" in overrides:
            overrides["expression_swap_rb"] = not overrides.pop("expression_no_swap_rb")
        if "aws_region" in overrides:
            overrides["cloud_expression"] = replace(config.cloud_expression, region=overrides.pop("aws_region"))
        config = replace(config, **overrides)
    except (ValueError, TypeError, OSError) as error:
        parser.error(str(error))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("phos.log", encoding="utf-8"),
        ],
    )
    asyncio.run(async_main(config=config))


if __name__ == "__main__":
    main()
