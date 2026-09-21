"""Start the PHOS robot runtime.

The default renderer opens the face fullscreen on the Pi's HDMI desktop.
"""

from __future__ import annotations

import asyncio
import argparse
import logging
import signal
import sys
from pathlib import Path

# Allow direct execution from a source checkout with
# ``python3 src/robot/main.py`` without a package installation.
SOURCE_DIRECTORY = Path(__file__).resolve().parent.parent
if str(SOURCE_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIRECTORY))

from robot import __version__
from robot.config import DEFAULT_CONFIG_PATH, ConfigurationError, RuntimeConfig, load_document
from robot.runtime import PhosRuntime, build_runtime
from robot.lifecycle import RESTART_EXIT_CODE

logger = logging.getLogger(__name__)


def build_application(*, config: RuntimeConfig | None = None) -> PhosRuntime:
    """Compose the single PHOS application/runtime coordinator."""
    return build_runtime(config=config)


def _install_shutdown_handlers(loop: asyncio.AbstractEventLoop, stop_event: asyncio.Event) -> None:
    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(shutdown_signal, stop_event.set)
        except NotImplementedError:
            # Signal handlers are unavailable on some event-loop platforms.
            pass


async def async_main(*, config: RuntimeConfig | None = None, lifecycle=None) -> None:
    stop_event = asyncio.Event()
    _install_shutdown_handlers(asyncio.get_running_loop(), stop_event)
    async def watch_restart():
        while not stop_event.is_set():
            if lifecycle is not None and lifecycle.restart_due:
                stop_event.set()
                return
            await asyncio.sleep(.1)
    watcher = asyncio.create_task(watch_restart()) if lifecycle is not None else None
    try:
        await build_application(config=config).run(stop_event)
    finally:
        if watcher is not None:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the PHOS robot runtime.",
                                     argument_default=argparse.SUPPRESS,
                                     epilog="All individual setting flags are deprecated overrides; edit the JSON file instead.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="canonical PHOS JSON configuration (default: config/phos.json)")
    parser.add_argument("--expression-provider", choices=("local", "aws"), help="deprecated: override expression.provider and enable expressions")
    parser.add_argument("--aws-region", help="deprecated: override expression.aws.region")
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
        help="ONNX model input size as WIDTHxHEIGHT (overrides expression.local.input_size)",
    )
    parser.add_argument(
        "--expression-scale",
        type=float,
        help="OpenCV DNN image scale for the expression model (overrides expression.local.scale)",
    )
    parser.add_argument(
        "--expression-mean",
        help="three OpenCV DNN image-mean values (overrides expression.local.mean)",
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
        help="square face crop margin per side, as a face-size fraction (0 to 0.5)",
    )
    arguments = vars(parser.parse_args())
    config_path = arguments.pop("config")
    try:
        # Compatibility flags become typed overrides of the one JSON model.
        # No flag supplies a separate default or persists its override.
        aliases = {"face_tracking": "face_tracking_enabled", "expression_model": "expression_model_path",
                   "expression_debug": "expression_diagnostics"}
        overrides = {aliases.get(name, name): value for name, value in arguments.items()}
        if "expression_labels" in overrides:
            overrides["expression_labels"] = tuple(v.strip() for v in overrides["expression_labels"].split(",") if v.strip())
        if "expression_input_size" in overrides:
            overrides["expression_input_size"] = tuple(int(v) for v in overrides["expression_input_size"].lower().split("x"))
        if "expression_mean" in overrides:
            overrides["expression_mean"] = tuple(float(v) for v in overrides["expression_mean"].split(","))
        if "expression_no_swap_rb" in overrides:
            overrides["expression_swap_rb"] = not overrides.pop("expression_no_swap_rb")
        if "expression_model_path" in overrides:
            overrides["expression_model_path"] = overrides["expression_model_path"].resolve()
            overrides["expression_enabled"] = True
        if "expression_provider" in overrides:
            overrides["expression_enabled"] = True
        # Region is an ordinary nested setting, resolved before model construction.
        document = load_document(config_path)
        if "aws_region" in overrides:
            if not isinstance(document, dict) or not isinstance(document.get("expression"), dict) or not isinstance(document["expression"].get("aws"), dict):
                raise ConfigurationError("expression.aws section is required")
            document["expression"]["aws"]["region"] = overrides.pop("aws_region")
        config = RuntimeConfig.from_dict(document, base_dir=config_path.resolve().parent, overrides=overrides)
    except (ValueError, TypeError, OSError) as error:
        parser.error(str(error))
    handlers = [logging.StreamHandler(sys.stdout)]
    if config.log_file is not None:
        try:
            handlers.append(logging.FileHandler(config.resolve_path(config.log_file), encoding="utf-8"))
        except OSError:
            parser.error("Cannot open logging.file; check its path and permissions")
    logging.basicConfig(level=config.log_level, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
    # Prevent SDK debug logs from exposing credential/signature details even when
    # PHOS diagnostics are enabled. Adapter logs contain only sanitized metadata.
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    if arguments:
        logger.warning("Individual runtime CLI flags are deprecated; edit %s instead", config_path)
    logger.info("PHOS %s", __version__)
    logger.info("PHOS configuration loaded: %s", config_path.resolve())
    # The optional web worker is isolated from camera/rendering and is stopped
    # even when runtime startup or execution fails.
    from robot.web.server import WebServer
    with WebServer(config_path, config) as web:
        asyncio.run(async_main(config=config, lifecycle=web.lifecycle))
    if web.lifecycle.restart_at is not None:
        raise SystemExit(RESTART_EXIT_CODE)



if __name__ == "__main__":
    main()
