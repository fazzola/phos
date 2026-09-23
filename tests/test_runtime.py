import asyncio
from pathlib import Path

import pytest

from robot.core import RobotState
from robot.runtime import RuntimeConfig, build_runtime
from robot.ui import FaceExpression, MemoryEyeDisplay, VisualAccent
from robot.vision import ExpressionObservation, ExpressionSmoother, FaceRegion, VisionPipeline


class FakeFrame:
    shape = (480, 640, 3)

    def __getitem__(self, item):
        return item


class FakeCamera:
    def __init__(self, *, fail=False, block=False):
        self.fail = fail
        self.block = block
        self.started = False
        self.stopped = False
        self.captures = 0
        self.release = asyncio.Event()

    async def start(self):
        self.started = True

    async def capture_frame(self):
        self.captures += 1
        if self.fail:
            raise RuntimeError("camera unavailable")
        if self.block:
            await self.release.wait()
        return FakeFrame()

    async def stop(self):
        self.stopped = True
        self.release.set()


class FakeFaceDetector:
    def __init__(self, faces):
        self.faces = faces

    async def detect(self, frame):
        return self.faces


class FakeExpressionProvider:
    def __init__(self, observation):
        self.observation = observation
        self.calls = 0

    async def classify(self, face_crop):
        self.calls += 1
        return self.observation


class FailingInitialDrawDisplay(MemoryEyeDisplay):
    def __init__(self):
        super().__init__()
        self.closed = False

    def draw(self, frame):
        raise RuntimeError("display unavailable")

    def close(self):
        self.closed = True


def make_vision(events, camera, *, faces=None, observation=None):
    return VisionPipeline(
        camera,
        FakeFaceDetector([FaceRegion(100, 100, 120, 120)] if faces is None else faces),
        FakeExpressionProvider(observation or ExpressionObservation("happy", 0.9, (("happy", 0.9), ("neutral", 0.1)))),
        ExpressionSmoother(minimum_observations=1),
        events=events,
        capture_interval_seconds=0.002,
        detection_interval_seconds=0.002,
        expression_interval_seconds=0.002,
    )


def make_face_tracking(events, camera, *, faces=None):
    return VisionPipeline(
        camera,
        FakeFaceDetector([FaceRegion(440, 120, 80, 120)] if faces is None else faces),
        None,
        None,
        events=events,
        capture_interval_seconds=0.002,
        detection_interval_seconds=0.002,
        expression_interval_seconds=0.002,
    )


def test_runtime_starts_and_stops_vision_camera_and_display():
    async def exercise():
        camera = FakeCamera()
        display = MemoryEyeDisplay()
        runtime = build_runtime(eye_display=display, vision_factory=lambda events: make_vision(events, camera))
        await runtime.start()
        await asyncio.sleep(0.02)
        await runtime.stop()
        return runtime, camera, display

    runtime, camera, display = asyncio.run(exercise())
    assert not runtime.core.is_running
    assert camera.started and camera.stopped
    assert display.frames


def test_reloading_iris_appearance_updates_running_renderer_without_restarting_runtime(tmp_path):
    import json
    from robot.config import load_document
    from robot.lifecycle import LifecycleService

    class StableVision:
        def __init__(self):
            self.started = False
            self.stopped = False
            self.release = asyncio.Event()

        async def start(self):
            self.started = True

        async def stop(self):
            self.stopped = True
            self.release.set()

        async def wait(self):
            await self.release.wait()

        def configure_preview(self, enabled):
            self.preview_enabled = enabled

    async def exercise():
        document = load_document()
        document["display"]["iris_color"] = "cyan"
        path = tmp_path / "phos.json"
        path.write_text(json.dumps(document))
        config = RuntimeConfig.from_file(path)
        display, vision = MemoryEyeDisplay(), StableVision()
        runtime = build_runtime(config=config, eye_display=display, vision_pipeline=vision)
        renderer = runtime._eye_render_loop._renderer
        behavior = runtime._behavior_engine
        await runtime.start()
        service = LifecycleService(path, config, log_level_setter=lambda _level: None)
        service.register_appearance_applier(runtime.apply_appearance)
        service.register_camera_preview_applier(runtime.apply_camera_preview)
        document["display"]["iris_color"] = "violet"
        document["vision"]["camera_preview"]["position"] = "top_left"
        path.write_text(json.dumps(document))
        result = await asyncio.to_thread(service.execute, "reload")
        await asyncio.sleep(.25)
        applied = display.frames[-1].iris_color
        still_running = runtime.core.is_running and vision.started and not vision.stopped
        same_renderer = runtime._eye_render_loop._renderer is renderer
        same_behavior = runtime._behavior_engine is behavior
        same_vision = runtime._vision_pipeline is vision
        selected_theme = renderer.iris_color
        selected_preview_position = runtime._eye_render_loop._preview_settings.position
        await runtime.stop()
        return result, applied, still_running, same_renderer, same_behavior, same_vision, selected_theme, selected_preview_position

    result, applied, still_running, same_renderer, same_behavior, same_vision, selected_theme, selected_preview_position = asyncio.run(exercise())
    assert result["applied"] == ["display.iris_color", "vision.camera_preview.position"]
    assert applied != "#28CEEB"  # Selected violet theme with the current semantic tint.
    assert selected_theme == "violet"
    assert selected_preview_position == "top_left"
    assert still_running and same_renderer and same_behavior and same_vision


def test_face_tracking_config_builds_camera_pipeline_without_expression_model():
    runtime = build_runtime(
        config=RuntimeConfig(face_tracking_enabled=True),
        eye_display=MemoryEyeDisplay(),
    )

    assert runtime._vision_pipeline is not None
    assert runtime._vision_pipeline._expression_provider is None


def test_ferplus_runtime_configuration_builds_a_grayscale_expression_provider(tmp_path):
    model = tmp_path / "test.onnx"
    model.write_bytes(b"model-file-placeholder")
    runtime = build_runtime(
        config=RuntimeConfig(
            expression_model_path=model,
            expression_labels=(
                "neutral",
                "happiness",
                "surprise",
                "sadness",
                "anger",
                "disgust",
                "fear",
                "contempt",
            ),
            expression_input_size=(64, 64),
            expression_scale=1.0,
            expression_mean=(0.0, 0.0, 0.0),
            expression_swap_rb=False,
            expression_grayscale=True,
        ),
        eye_display=MemoryEyeDisplay(),
    )

    provider = runtime._vision_pipeline._expression_provider
    assert provider._input_size == (64, 64)
    assert provider._scale == 1.0
    assert provider._swap_rb is False
    assert provider._grayscale is True


def test_stable_vision_observation_reaches_behavior_engine_and_renderer():
    async def exercise():
        display = MemoryEyeDisplay()
        runtime = build_runtime(
            eye_display=display,
            vision_factory=lambda events: make_vision(events, FakeCamera()),
        )
        await runtime.start()
        await asyncio.sleep(0.9)
        state = runtime._behavior_engine.face_state
        await runtime.stop()
        return state, display

    state, display = asyncio.run(exercise())
    assert state.expression is FaceExpression.HAPPY
    assert state.accent is VisualAccent.WARM
    assert 0.0 < state.reaction_strength <= 0.90
    assert len(display.frames) >= 2


def test_face_tracking_reaches_behavior_engine_without_expression_reactions():
    async def exercise():
        display = MemoryEyeDisplay()
        runtime = build_runtime(
            eye_display=display,
            vision_factory=lambda events: make_face_tracking(events, FakeCamera()),
        )
        await runtime.start()
        async def wait_for_gaze():
            while True:
                state = runtime._behavior_engine.face_state
                if state.pupil_x > 0.3 and state.pupil_y < -0.1 and len(display.frames) >= 2:
                    return state
                await asyncio.sleep(.01)
        try:
            state = await asyncio.wait_for(wait_for_gaze(), timeout=1)
        finally:
            await runtime.stop()
        return state, display

    state, display = asyncio.run(exercise())
    assert state.expression is FaceExpression.NEUTRAL
    assert state.pupil_x > 0.3
    assert state.pupil_y < -0.1
    assert len(display.frames) >= 2


def test_sleeping_state_overrides_stable_vision_reaction():
    async def exercise():
        runtime = build_runtime(
            eye_display=MemoryEyeDisplay(),
            vision_factory=lambda events: make_vision(events, FakeCamera()),
        )
        await runtime.start()
        await runtime.core.transition_to(RobotState.SLEEPING)
        await asyncio.sleep(0.03)
        state = runtime._behavior_engine.face_state
        await runtime.stop()
        return state

    state = asyncio.run(exercise())
    assert state.expression is FaceExpression.SLEEPY


def test_no_face_condition_keeps_default_idle_face():
    async def exercise():
        runtime = build_runtime(
            eye_display=MemoryEyeDisplay(),
            vision_factory=lambda events: make_vision(events, FakeCamera(), faces=[]),
        )
        await runtime.start()
        await asyncio.sleep(0.02)
        state = runtime._behavior_engine.face_state
        await runtime.stop()
        return state

    state = asyncio.run(exercise())
    assert state.expression is FaceExpression.NEUTRAL


def test_renderer_keeps_updating_while_vision_capture_is_blocked():
    async def exercise():
        camera = FakeCamera(block=True)
        display = MemoryEyeDisplay()
        runtime = build_runtime(eye_display=display, vision_factory=lambda events: make_vision(events, camera))
        await runtime.start()
        await asyncio.sleep(0.08)
        frames = len(display.frames)
        await runtime.stop()
        return frames

    assert asyncio.run(exercise()) >= 2


def test_vision_failure_transitions_to_error_and_releases_camera():
    async def exercise():
        camera = FakeCamera(fail=True)
        runtime = build_runtime(
            config=RuntimeConfig(display_fps=30, fullscreen=False),
            eye_display=MemoryEyeDisplay(),
            vision_factory=lambda events: make_vision(events, camera),
        )
        with pytest.raises(RuntimeError, match="camera unavailable"):
            await runtime.run(asyncio.Event())
        return runtime.core.state, camera

    state, camera = asyncio.run(exercise())
    assert state is RobotState.ERROR
    assert camera.stopped


def test_display_startup_failure_closes_display_and_rolls_back_core():
    async def exercise():
        display = FailingInitialDrawDisplay()
        runtime = build_runtime(eye_display=display)
        with pytest.raises(RuntimeError, match="display unavailable"):
            await runtime.start()
        return runtime, display

    runtime, display = asyncio.run(exercise())
    assert display.closed
    assert not runtime.core.is_running


def test_runtime_passes_configurable_margin_to_vision_pipeline():
    runtime = build_runtime(config=RuntimeConfig(face_tracking_enabled=True, expression_crop_margin=0.2),
                            eye_display=MemoryEyeDisplay())
    assert runtime._vision_pipeline._crop_margin == 0.2


@pytest.mark.parametrize('margin', [-0.1, 0.6, float('nan'), float('inf')])
def test_runtime_rejects_invalid_crop_margin(margin):
    with pytest.raises(ValueError, match='expression_crop_margin'):
        RuntimeConfig(expression_crop_margin=margin)


@pytest.mark.parametrize("cancel", [False, True])
def test_partial_vision_startup_releases_camera_and_core(cancel):
    async def exercise():
        entered = asyncio.Event()
        class StartingCamera(FakeCamera):
            async def start(self):
                self.started = True
                entered.set()
                if cancel:
                    await asyncio.Event().wait()
                raise RuntimeError("camera startup failed")
        camera = StartingCamera()
        runtime = build_runtime(eye_display=MemoryEyeDisplay(),
                                vision_factory=lambda events: make_vision(events, camera))
        task = asyncio.create_task(runtime.start())
        await entered.wait()
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
            await task
        assert camera.stopped and not runtime.core.is_running
        assert not runtime._unsubscribers
    asyncio.run(exercise())


def test_preview_only_reload_starts_stops_and_restarts_one_camera(monkeypatch, tmp_path):
    from robot.config import load_document
    import json

    async def exercise():
        camera = FakeCamera()
        pipeline = make_face_tracking(None, camera)
        monkeypatch.setattr('robot.runtime._build_configured_vision', lambda *args: pipeline)
        # Exercise config-relative paths, which dataclasses.replace would rebase.
        document = load_document()
        document['logging']['file'] = 'runtime.log'
        path = tmp_path / 'phos.json'
        path.write_text(json.dumps(document))
        config = RuntimeConfig.from_file(path)
        runtime = build_runtime(config=config, eye_display=MemoryEyeDisplay())
        stop = asyncio.Event()
        runner = asyncio.create_task(runtime.run(stop))
        while not runtime._started:
            await asyncio.sleep(0)
        enabled = RuntimeConfig.from_dict(config.to_dict(), base_dir=tmp_path,
                                          overrides={'camera_preview_enabled': True})
        for _ in range(2):
            await asyncio.to_thread(runtime.apply_camera_preview, enabled)
            await asyncio.sleep(.02)
            assert runtime._vision_started and pipeline.preview_snapshot is not None
            assert runtime._config.resolve_path(runtime._config.log_file) == tmp_path / 'runtime.log'
            await asyncio.to_thread(runtime.apply_camera_preview, config)
            await asyncio.sleep(.02)
            assert not runtime._vision_started and pipeline.preview_snapshot is None
            assert not runner.done()
        stop.set()
        await runner
        assert not runtime._preview_tasks
        # Supervisor child waiters must be cancelled, not abandoned on shutdown.
        assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
    asyncio.run(exercise())


def test_failed_preview_reload_releases_camera_and_does_not_report_applied(monkeypatch, tmp_path):
    import json
    from robot.config import load_document
    from robot.lifecycle import LifecycleService

    async def exercise():
        class FailingCamera(FakeCamera):
            async def start(self):
                self.started = True
                raise RuntimeError('camera startup failed')
        camera = FailingCamera()
        pipeline = make_face_tracking(None, camera)
        monkeypatch.setattr('robot.runtime._build_configured_vision', lambda *args: pipeline)
        document = load_document()
        document['logging']['file'] = None
        path = tmp_path / 'phos.json'
        path.write_text(json.dumps(document))
        config = RuntimeConfig.from_file(path)
        runtime = build_runtime(config=config, eye_display=MemoryEyeDisplay())
        await runtime.start()
        service = LifecycleService(path, config)
        service.register_camera_preview_applier(runtime.apply_camera_preview)
        document['vision']['camera_preview']['enabled'] = True
        path.write_text(json.dumps(document))
        result = await asyncio.to_thread(service.execute, 'reload')
        assert not result['ok'] and not result['applied']
        assert not service.active['vision']['camera_preview']['enabled']
        assert not runtime._config.camera_preview_enabled
        assert camera.started and camera.stopped
        assert runtime.core.is_running and not runtime._vision_started
        await runtime.stop()
    asyncio.run(exercise())


def test_shutdown_cancels_inflight_preview_start_and_releases_camera(monkeypatch):
    async def exercise():
        entered = asyncio.Event()
        class SlowCamera(FakeCamera):
            async def start(self):
                self.started = True
                entered.set()
                await asyncio.Event().wait()
        camera = SlowCamera()
        pipeline = make_face_tracking(None, camera)
        monkeypatch.setattr('robot.runtime._build_configured_vision', lambda *args: pipeline)
        runtime = build_runtime(config=RuntimeConfig(), eye_display=MemoryEyeDisplay())
        await runtime.start()
        reload = asyncio.create_task(asyncio.to_thread(runtime.apply_camera_preview,
                                                       RuntimeConfig(camera_preview_enabled=True)))
        await asyncio.wait_for(entered.wait(), 1)
        await runtime.stop()
        result = await asyncio.gather(reload, return_exceptions=True)
        assert isinstance(result[0], BaseException)
        assert camera.stopped and not runtime._preview_tasks
        assert not runtime.core.is_running
        with pytest.raises(RuntimeError, match='not ready'):
            runtime.apply_camera_preview(RuntimeConfig())
    asyncio.run(exercise())
