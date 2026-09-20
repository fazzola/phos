"""Thin application coordinator for Core, Vision, behavior, and display."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

from robot.config import RuntimeConfig
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

from robot.vision.aws_expression import AWSExpressionProvider

logger = logging.getLogger(__name__)


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
    config: Optional[RuntimeConfig] = None,
    eye_display: Optional[EyeDisplay] = None,
    vision_pipeline: Optional[VisionPipeline] = None,
    vision_factory: Optional[Callable[[EventBus], VisionPipeline]] = None,
) -> PhosRuntime:
    """Compose a runtime; tests may inject a fake VisionPipeline/display."""
    if vision_pipeline is not None and vision_factory is not None:
        raise ValueError("Provide either vision_pipeline or vision_factory, not both.")
    config = RuntimeConfig.from_file() if config is None else config
    config.validate()
    config.validate_paths()
    core = RobotCore()
    behavior_engine = BehaviorEngine(
        core.events, blink_interval=config.blink_interval_seconds,
        gaze_interval=config.gaze_interval_seconds, face_gaze_smoothing=config.face_gaze_smoothing,
        reaction_decay_per_second=config.reaction_decay_per_second,
    )
    eye_render_loop = EyeRenderLoop(
        EyeRenderer(width=config.display_width, height=config.display_height,
                    transition_seconds=config.display_transition_seconds),
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
    if config.expression_enabled and config.expression_provider == "aws":
        expression_provider = AWSExpressionProvider(config.cloud_expression, diagnostics=config.expression_diagnostics)
        smoother = ExpressionSmoother(
            minimum_confidence=config.expression_minimum_confidence,
            minimum_observations=config.expression_minimum_observations,
            neutral_enabled=config.expression_neutral_enabled,
            maximum_gap_seconds=config.cloud_expression.cache_ttl_seconds,
        )
    elif config.expression_enabled:
        expression_provider = OpenCVExpressionProvider(
            config.resolve_path(config.expression_model_path),
            config.expression_labels,
            input_size=config.expression_input_size,
            scale=config.expression_scale,
            mean=config.expression_mean,
            swap_rb=config.expression_swap_rb,
            grayscale=config.expression_grayscale,
            diagnostics=config.expression_diagnostics,
        )
        smoother = ExpressionSmoother(
            minimum_confidence=config.expression_minimum_confidence,
            minimum_observations=config.expression_minimum_observations,
            maximum_gap_seconds=config.expression_local_maximum_gap_seconds,
            neutral_enabled=config.expression_neutral_enabled,
        )
    logger.info("Expression provider: %s", config.expression_provider if expression_provider else "disabled")
    return VisionPipeline(
        Picamera2CameraProvider(config.camera_resolution),
        OpenCVFaceDetector(
            config.resolve_path(config.cascade_path), scale_factor=config.detector_scale_factor,
            min_neighbors=config.detector_min_neighbors, min_size=config.detector_min_size,
        ),
        expression_provider,
        smoother,
        events=events,
        capture_interval_seconds=1.0 / config.vision_capture_fps,
        detection_interval_seconds=1.0 / config.face_detection_fps,
        expression_interval_seconds=1.0 / config.expression_inference_fps,
        diagnostics=config.expression_diagnostics,
        crop_margin=config.expression_crop_margin,
    )
