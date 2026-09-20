"""Thin application coordinator for Core, Vision, behavior, and display."""

from __future__ import annotations

import asyncio
import logging
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Tuple

from robot.core import BehaviorEngine, Event, EventBus, RobotCore, RobotState, STATE_CHANGED
from robot.ui import EyeDisplay, EyeRenderer, TkEyeDisplay
from robot.ui.runtime import EyeRenderLoop
from robot.vision import (
    ExpressionSmoother,
    OpenCVExpressionProvider,
    OpenCVFaceDetector,
    Picamera2CameraProvider,
    VisionPipeline,
)

from robot.vision.aws_expression import AWSExpressionProvider, CloudExpressionConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeConfig:
    """Small configuration surface for the first integrated runtime."""

    display_fps: int = 30
    fullscreen: bool = True
    face_tracking_enabled: bool = False
    camera_resolution: Tuple[int, int] = (640, 480)
    vision_capture_fps: float = 15.0
    face_detection_fps: float = 4.0
    expression_inference_fps: float = 3.0
    expression_provider: str = "local"
    cloud_expression: CloudExpressionConfig = field(default_factory=CloudExpressionConfig)
    expression_minimum_confidence: float = 0.60
    expression_model_path: Optional[Path] = None
    expression_labels: Tuple[str, ...] = ()
    expression_input_size: Tuple[int, int] = (64, 64)
    expression_scale: float = 1.0 / 255.0
    expression_mean: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    expression_swap_rb: bool = True
    expression_grayscale: bool = False
    expression_diagnostics: bool = False
    expression_crop_margin: float = 0.10

    def __post_init__(self) -> None:
        if self.expression_provider not in {"local", "aws"}:
            raise ValueError("expression_provider must be local or aws")
        if not isinstance(self.cloud_expression, CloudExpressionConfig):
            raise ValueError("cloud_expression must be CloudExpressionConfig")
        if not math.isfinite(self.expression_minimum_confidence) or not 0 <= self.expression_minimum_confidence <= 1:
            raise ValueError("expression_minimum_confidence must be between zero and one")
        if not math.isfinite(self.expression_crop_margin) or not 0 <= self.expression_crop_margin <= 0.5:
            raise ValueError("expression_crop_margin must be between zero and 0.5.")
        for name in ("display_fps", "vision_capture_fps", "face_detection_fps", "expression_inference_fps"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        for name in ("camera_resolution", "expression_input_size"):
            values = getattr(self, name)
            if len(values) != 2 or any(type(v) is not int or v <= 0 for v in values):
                raise ValueError(f"{name} must contain two positive integers")
        for name in ("fullscreen", "face_tracking_enabled", "expression_swap_rb", "expression_grayscale", "expression_diagnostics"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        if self.expression_model_path is None and self.expression_labels:
            raise ValueError("expression_labels require expression_model_path.")
        if self.expression_model_path is not None and not self.expression_labels:
            raise ValueError("expression_model_path requires configured expression_labels.")
        if any(not isinstance(label, str) or not label.strip() for label in self.expression_labels):
            raise ValueError("expression_labels must contain nonempty strings")
        if len(self.expression_mean) != 3 or any(not math.isfinite(v) for v in self.expression_mean):
            raise ValueError("expression_mean must contain three finite channel values.")
        if not math.isfinite(self.expression_scale):
            raise ValueError("expression_scale must be finite")

    @classmethod
    def from_file(cls, path: Path) -> RuntimeConfig:
        """Load ordinary settings into the existing typed configuration boundary."""
        values = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(values, dict):
            raise ValueError("Runtime configuration must be a JSON object")
        if "cloud_expression" in values:
            values["cloud_expression"] = CloudExpressionConfig(**values["cloud_expression"])
        if values.get("expression_model_path") is not None:
            values["expression_model_path"] = Path(values["expression_model_path"])
        for name in ("camera_resolution", "expression_labels", "expression_input_size", "expression_mean"):
            if name in values:
                values[name] = tuple(values[name])
        return cls(**values)

    @property
    def vision_enabled(self) -> bool:
        return self.face_tracking_enabled or self.expression_model_path is not None or self.expression_provider == "aws"


class PhosRuntime:
    """Own application lifecycle without embedding Vision or UI implementation."""

    def __init__(
        self,
        core: RobotCore,
        behavior_engine: BehaviorEngine,
        eye_render_loop: EyeRenderLoop,
        *,
        vision_pipeline: Optional[VisionPipeline] = None,
    ) -> None:
        self.core = core
        self._behavior_engine = behavior_engine
        self._eye_render_loop = eye_render_loop
        self._vision_pipeline = vision_pipeline
        self._unsubscribers: list[Callable[[], None]] = []
        self._started = False
        self._vision_started = False

    async def start(self) -> None:
        if self._started:
            raise RuntimeError("PHOS runtime is already running.")
        self._unsubscribers = [self.core.events.subscribe(STATE_CHANGED, self._log_state_transition)]
        try:
            await self.core.start()
            logger.info("PHOS core, behavior engine, and renderer started")
            if self._vision_pipeline is not None:
                await self._vision_pipeline.start()
                self._vision_started = True
                logger.info("PHOS vision pipeline and camera started")
            self._started = True
            logger.info("PHOS runtime started")
        except Exception:
            logger.exception("PHOS runtime failed during startup")
            await self._transition_to_error("runtime startup failure")
            await self.stop()
            raise

    async def run(self, stop_event: asyncio.Event) -> None:
        """Run until requested to stop or a supervised subsystem fails."""
        await self.start()
        stop_task = asyncio.create_task(stop_event.wait(), name="runtime-stop-request")
        supervisors = [
            asyncio.create_task(self._behavior_engine.wait(), name="behavior-engine-supervisor"),
            asyncio.create_task(self._eye_render_loop.wait(), name="eye-render-supervisor"),
        ]
        if self._vision_pipeline is not None:
            supervisors.append(asyncio.create_task(self._vision_pipeline.wait(), name="vision-supervisor"))
        try:
            done, _pending = await asyncio.wait([stop_task, *supervisors], return_when=asyncio.FIRST_COMPLETED)
            if stop_task not in done:
                failed = next(task for task in done if task in supervisors)
                try:
                    failed.result()
                    raise RuntimeError("A PHOS subsystem stopped unexpectedly.")
                except asyncio.CancelledError:
                    raise RuntimeError("A PHOS subsystem was cancelled unexpectedly.")
                except Exception as error:
                    logger.exception("PHOS subsystem failed", exc_info=error)
                    await self._transition_to_error(type(error).__name__)
        finally:
            for task in [stop_task, *supervisors]:
                if not task.done():
                    task.cancel()
            await asyncio.gather(stop_task, *supervisors, return_exceptions=True)
            await self.stop()

    async def stop(self) -> None:
        if self._vision_started and self._vision_pipeline is not None:
            try:
                await self._vision_pipeline.stop()
            except Exception:
                logger.exception("PHOS vision shutdown failed")
            self._vision_started = False
            logger.info("PHOS vision pipeline stopped")
        if self.core.is_running:
            try:
                await self.core.stop()
            except Exception:
                logger.exception("PHOS core shutdown failed")
            logger.info("PHOS core, renderer, and behavior engine stopped")
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers = []
        self._started = False
        logger.info("PHOS runtime stopped")

    async def _transition_to_error(self, reason: str) -> None:
        if self.core.is_running and self.core.state is not RobotState.ERROR:
            try:
                await self.core.transition_to(RobotState.ERROR, reason=reason)
            except Exception:
                logger.exception("Could not transition PHOS core to ERROR")

    @staticmethod
    def _log_state_transition(event: Event) -> None:
        logger.info("PHOS state changed to %s", event.data.get("current"))


def build_runtime(
    *,
    config: RuntimeConfig = RuntimeConfig(),
    eye_display: Optional[EyeDisplay] = None,
    vision_pipeline: Optional[VisionPipeline] = None,
    vision_factory: Optional[Callable[[EventBus], VisionPipeline]] = None,
) -> PhosRuntime:
    """Compose a runtime; tests may inject a fake VisionPipeline/display."""
    if vision_pipeline is not None and vision_factory is not None:
        raise ValueError("Provide either vision_pipeline or vision_factory, not both.")
    core = RobotCore()
    behavior_engine = BehaviorEngine(core.events)
    eye_render_loop = EyeRenderLoop(
        EyeRenderer(),
        eye_display or TkEyeDisplay(),
        lambda: behavior_engine.face_state,
        fps=config.display_fps,
        fullscreen=config.fullscreen,
    )
    core.add_behavior(behavior_engine)
    core.add_behavior(eye_render_loop)
    resolved_vision = vision_pipeline or (
        vision_factory(core.events) if vision_factory is not None else _build_configured_vision(config, core.events)
    )
    return PhosRuntime(core, behavior_engine, eye_render_loop, vision_pipeline=resolved_vision)


def _build_configured_vision(config: RuntimeConfig, events: EventBus) -> Optional[VisionPipeline]:
    if not config.vision_enabled:
        return None
    expression_provider = None
    smoother = None
    if config.expression_provider == "aws":
        expression_provider = AWSExpressionProvider(config.cloud_expression, diagnostics=config.expression_diagnostics)
        smoother = ExpressionSmoother(
            minimum_confidence=config.expression_minimum_confidence,
            maximum_gap_seconds=config.cloud_expression.cache_ttl_seconds,
        )
    elif config.expression_model_path is not None:
        expression_provider = OpenCVExpressionProvider(
            config.expression_model_path,
            config.expression_labels,
            input_size=config.expression_input_size,
            scale=config.expression_scale,
            mean=config.expression_mean,
            swap_rb=config.expression_swap_rb,
            grayscale=config.expression_grayscale,
            diagnostics=config.expression_diagnostics,
        )
        smoother = ExpressionSmoother(minimum_confidence=config.expression_minimum_confidence)
    logger.info("Expression provider: %s", config.expression_provider if expression_provider else "disabled")
    return VisionPipeline(
        Picamera2CameraProvider(config.camera_resolution),
        OpenCVFaceDetector(),
        expression_provider,
        smoother,
        events=events,
        capture_interval_seconds=1.0 / config.vision_capture_fps,
        detection_interval_seconds=1.0 / config.face_detection_fps,
        expression_interval_seconds=1.0 / config.expression_inference_fps,
        diagnostics=config.expression_diagnostics,
        crop_margin=config.expression_crop_margin,
    )
