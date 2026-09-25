"""Thin application coordinator for Core, Vision, behavior, and display."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

from robot.config import RuntimeConfig
from robot.hardware.environmental import environmental_provider_type
from robot.hardware.ccs811 import CCS811Provider
from robot.hardware.mpu6050 import MPU6050Provider
from robot.sensors import (EnvironmentalSensorProvider, EnvironmentalSensorService,
                           AirQualitySensorProvider, AirQualitySensorService,
                           IMUSensorProvider, IMUSensorService)
from robot.core import BehaviorEngine, Event, EventBus, RobotCore, RobotState, STATE_CHANGED
from robot.ui import CameraPreviewSettings, CameraPreviewView, EyeDisplay, EyeRenderer, TkEyeDisplay
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
        config: Optional[RuntimeConfig] = None,
        vision_forced: bool = False,
        sensor_service: Optional[EnvironmentalSensorService] = None,
        air_quality_service: Optional[AirQualitySensorService] = None,
        imu_service: Optional[IMUSensorService] = None,
    ) -> None:
        self.core = core
        self._behavior_engine = behavior_engine
        self._eye_render_loop = eye_render_loop
        self._vision_pipeline = vision_pipeline
        self._config = config
        self._vision_forced = vision_forced
        self._sensor_service = sensor_service
        self._air_quality_service = air_quality_service
        self._imu_service = imu_service
        self._loop = None
        self._vision_changed: Optional[asyncio.Event] = None
        self._vision_lock = asyncio.Lock()
        self._preview_tasks = set()
        self._stopping = False
        self._unsubscribers: list[Callable[[], None]] = []
        self._started = False
        self._vision_started = False

    def apply_appearance(self, config: RuntimeConfig) -> None:
        """Apply validated appearance through the display runtime boundary."""
        self._eye_render_loop.request_appearance(iris_color=config.iris_color)

    def sensor_status(self) -> dict:
        """Read-only application boundary, safe for the lifecycle thread."""
        state = {"environmental": self._sensor_service.snapshot()} if self._sensor_service is not None else {}
        if self._air_quality_service is not None:
            state["ccs811"] = self._air_quality_service.snapshot()
        if self._imu_service is not None:
            state["imu"] = self._imu_service.snapshot()
        return state

    def apply_camera_preview(self, config: RuntimeConfig) -> None:
        """Apply from the lifecycle thread and acknowledge runtime acceptance."""
        loop = self._loop
        if loop is None or not self._started or self._stopping:
            raise RuntimeError("PHOS runtime is not ready for preview reload")
        try:
            caller_loop = asyncio.get_running_loop()
        except RuntimeError:
            caller_loop = None
        if caller_loop is loop:
            raise RuntimeError("Preview reload must use the lifecycle thread")
        future = asyncio.run_coroutine_threadsafe(self._apply_camera_preview(config), loop)
        # The IPC client bounds its response wait and reports an in-flight result
        # as uncertain. Keep this acknowledgement tied to actual completion:
        # native camera startup may outlast the HTTP request. Shutdown cancels
        # and drains the task, so it cannot start a camera after runtime exit.
        future.result()

    async def _apply_camera_preview(self, config):
        task = asyncio.current_task()
        self._preview_tasks.add(task)
        try:
            async with self._vision_lock:
                if self._stopping or not self._started:
                    raise RuntimeError("PHOS runtime is stopping")
                names = ("camera_preview_enabled", "camera_preview_position", "camera_preview_scale",
                         "camera_preview_max_fps", "camera_preview_show_face_box",
                         "camera_preview_show_expression", "camera_preview_show_confidence")
                previous = self._config
                updated = RuntimeConfig.from_dict(previous.to_dict(), base_dir=previous._base_dir,
                    overrides={name: getattr(config, name) for name in names})
                # Validate the effective configuration, retaining pending restart fields.
                self._config = updated
                try:
                    await self._reconcile_vision_preview()
                    self._eye_render_loop.request_preview_settings(_preview_settings(updated))
                except BaseException:
                    self._config = previous
                    if self._vision_pipeline is not None:
                        self._vision_pipeline.configure_preview(previous.camera_preview_enabled)
                    raise
        finally:
            self._preview_tasks.discard(task)

    async def _supervise_vision(self):
        while True:
            if not self._vision_started or self._vision_pipeline is None:
                if self._vision_changed is None:
                    return
                await self._vision_changed.wait()
                self._vision_changed.clear()
                continue
            wait_task = asyncio.create_task(self._vision_pipeline.wait())
            change_task = asyncio.create_task(self._vision_changed.wait())
            try:
                done, _ = await asyncio.wait((wait_task, change_task), return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in (wait_task, change_task):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(wait_task, change_task, return_exceptions=True)
            if change_task in done:
                self._vision_changed.clear()
                if not self._vision_started:
                    try:
                        await wait_task
                    except asyncio.CancelledError:
                        pass
                    continue
            if wait_task in done:
                try:
                    wait_task.result()
                    if self._vision_started:
                        raise RuntimeError("Vision pipeline stopped unexpectedly.")
                except asyncio.CancelledError:
                    if self._vision_started:
                        raise RuntimeError("Vision pipeline was cancelled unexpectedly.")

    async def _reconcile_vision_preview(self) -> None:
        if self._vision_pipeline is None or self._config is None:
            return
        configure_preview = getattr(self._vision_pipeline, "configure_preview", None)
        if configure_preview is not None:
            configure_preview(self._config.camera_preview_enabled)
        wanted = self._config.vision_enabled or self._vision_forced
        if wanted and not self._vision_started:
            self._vision_started = True
            try:
                await self._vision_pipeline.start()
                logger.info("PHOS vision pipeline started for camera preview")
            except BaseException:
                # Camera ownership may already have been acquired before failure.
                await self._vision_pipeline.stop()
                self._vision_started = False
                raise
            finally:
                self._vision_changed.set()
        elif not wanted and self._vision_started:
            # Tell the supervisor before awaiting stop, which completes wait().
            self._vision_started = False
            self._vision_changed.set()
            try:
                await self._vision_pipeline.stop()
            except BaseException:
                # Retain ownership so final shutdown retries cleanup.
                self._vision_started = True
                self._vision_changed.set()
                raise
            logger.info("PHOS vision pipeline stopped after preview was disabled")

    async def start(self) -> None:
        if self._started:
            raise RuntimeError("PHOS runtime is already running.")
        self._unsubscribers = [self.core.events.subscribe(STATE_CHANGED, self._log_state_transition)]
        self._stopping = False
        self._loop = asyncio.get_running_loop()
        self._vision_changed = asyncio.Event()
        try:
            await self.core.start()
            if self._sensor_service is not None:
                await self._sensor_service.start()
            if self._air_quality_service is not None:
                await self._air_quality_service.start()
            if self._imu_service is not None:
                await self._imu_service.start()
            logger.info("PHOS core, behavior engine, and renderer started")
            if self._vision_pipeline is not None and self._config is not None and (self._config.vision_enabled or self._vision_forced):
                # Stop must also release a partially started camera/pipeline.
                self._vision_started = True
                await self._vision_pipeline.start()
                logger.info("PHOS vision pipeline and camera started")
            self._started = True
            logger.info("PHOS runtime started")
        except asyncio.CancelledError:
            await self.stop()
            raise
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
            supervisors.append(asyncio.create_task(self._supervise_vision(), name="vision-supervisor"))
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
                    raise
        finally:
            for task in [stop_task, *supervisors]:
                if not task.done():
                    task.cancel()
            await asyncio.gather(stop_task, *supervisors, return_exceptions=True)
            await self.stop()

    async def stop(self) -> None:
        self._stopping = True
        tasks = tuple(self._preview_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._loop = None
        if self._air_quality_service is not None:
            await self._air_quality_service.stop()
        if self._imu_service is not None:
            await self._imu_service.stop()
        if self._sensor_service is not None:
            await self._sensor_service.stop()
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
    sensor_provider_factory: Optional[Callable[[], EnvironmentalSensorProvider]] = None,
    air_quality_provider_factory: Optional[Callable[[], AirQualitySensorProvider]] = None,
    imu_provider_factory: Optional[Callable[[], IMUSensorProvider]] = None,
) -> PhosRuntime:
    """Compose a runtime; tests may inject Vision, display and sensor providers."""
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
    vision_holder = {"pipeline": vision_pipeline}
    eye_render_loop = EyeRenderLoop(
        EyeRenderer(width=config.display_width, height=config.display_height,
                    transition_seconds=config.display_transition_seconds, iris_color=config.iris_color),
        eye_display or TkEyeDisplay(),
        lambda: behavior_engine.face_state,
        fps=config.display_fps,
        fullscreen=config.fullscreen,
        preview_supplier=lambda: _preview_view(vision_holder["pipeline"]),
        preview_settings=_preview_settings(config),
    )
    core.add_behavior(behavior_engine)
    core.add_behavior(eye_render_loop)
    injected_vision = vision_pipeline is not None or vision_factory is not None
    resolved_vision = vision_pipeline or (
        vision_factory(core.events) if vision_factory is not None else _build_configured_vision(config, core.events)
    )
    vision_holder["pipeline"] = resolved_vision
    provider_type = environmental_provider_type(config.environmental_type)
    sensors = EnvironmentalSensorService(
        sensor_provider_factory if sensor_provider_factory is not None else
        lambda: provider_type(address=int(config.environmental_i2c_address, 16)),
        sensor_type=config.environmental_type,
        available_measurements=provider_type.available_measurements,
        enabled=config.environmental_enabled,
        poll_interval_seconds=config.environmental_poll_interval_seconds,
        stale_after_seconds=config.environmental_stale_after_seconds,
    )
    if config.environmental_enabled:
        logger.info("%s enabled: I2C bus 1, address %s, polling every %s seconds",
                    config.environmental_type.upper(), config.environmental_i2c_address, config.environmental_poll_interval_seconds)
    air_quality = AirQualitySensorService(
        air_quality_provider_factory if air_quality_provider_factory is not None else
        lambda: CCS811Provider(address=int(config.ccs811_i2c_address, 16)),
        enabled=config.ccs811_enabled, poll_interval_seconds=config.ccs811_poll_interval_seconds,
        stale_after_seconds=config.ccs811_stale_after_seconds, compensation_supplier=sensors.compensation,
    )
    if config.ccs811_enabled:
        logger.info("CCS811 enabled: I2C bus 1, address %s, polling every %s seconds",
                    config.ccs811_i2c_address, config.ccs811_poll_interval_seconds)
    imu = IMUSensorService(
        imu_provider_factory if imu_provider_factory is not None else
        lambda: MPU6050Provider(address=int(config.imu_i2c_address, 16)),
        enabled=config.imu_enabled, poll_interval_seconds=config.imu_poll_interval_seconds,
        stale_after_seconds=config.imu_stale_after_seconds,
    )
    if config.imu_enabled:
        logger.info("MPU-6050 enabled: I2C bus 1, address %s, polling every %s seconds",
                    config.imu_i2c_address, config.imu_poll_interval_seconds)
    return PhosRuntime(core, behavior_engine, eye_render_loop, vision_pipeline=resolved_vision,
                       config=config, vision_forced=injected_vision, sensor_service=sensors,
                       air_quality_service=air_quality, imu_service=imu)


def _build_configured_vision(config: RuntimeConfig, events: EventBus) -> Optional[VisionPipeline]:
    # Construct a dormant owner for later preview reload; constructors do not
    # import camera/OpenCV dependencies or acquire hardware.
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
        preview_enabled=config.camera_preview_enabled,
        publish_face_position=config.face_tracking_enabled or config.expression_enabled,
    )


def _preview_settings(config):
    return CameraPreviewSettings(config.camera_preview_enabled, config.camera_preview_position,
        config.camera_preview_scale, config.camera_preview_max_fps,
        config.camera_preview_show_face_box, config.camera_preview_show_expression,
        config.camera_preview_show_confidence)


def _preview_view(pipeline):
    snapshot = getattr(pipeline, "preview_snapshot", None) if pipeline is not None else None
    if snapshot is None:
        return None
    face = snapshot.face
    return CameraPreviewView(snapshot.frame,
        None if face is None else (face.x, face.y, face.width, face.height),
        snapshot.raw_expression, snapshot.confidence, snapshot.semantic_expression)
