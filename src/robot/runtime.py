"""Thin application coordinator for Core, Vision, behavior, and display."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
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
    expression_model_path: Optional[Path] = None
    expression_labels: Tuple[str, ...] = ()
    expression_input_size: Tuple[int, int] = (64, 64)

    def __post_init__(self) -> None:
        if self.display_fps <= 0:
            raise ValueError("display_fps must be positive.")
        if self.camera_resolution[0] <= 0 or self.camera_resolution[1] <= 0:
            raise ValueError("camera_resolution values must be positive.")
        if min(self.vision_capture_fps, self.face_detection_fps, self.expression_inference_fps) <= 0:
            raise ValueError("Vision frequencies must be positive.")
        if self.expression_model_path is None and self.expression_labels:
            raise ValueError("expression_labels require expression_model_path.")
        if self.expression_model_path is not None and not self.expression_labels:
            raise ValueError("expression_model_path requires configured expression_labels.")

    @property
    def vision_enabled(self) -> bool:
        return self.face_tracking_enabled or self.expression_model_path is not None


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
    if config.expression_model_path is not None:
        expression_provider = OpenCVExpressionProvider(
            config.expression_model_path,
            config.expression_labels,
            input_size=config.expression_input_size,
        )
        smoother = ExpressionSmoother()
    return VisionPipeline(
        Picamera2CameraProvider(config.camera_resolution),
        OpenCVFaceDetector(),
        expression_provider,
        smoother,
        events=events,
        capture_interval_seconds=1.0 / config.vision_capture_fps,
        detection_interval_seconds=1.0 / config.face_detection_fps,
        expression_interval_seconds=1.0 / config.expression_inference_fps,
    )
