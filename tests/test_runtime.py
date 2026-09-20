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
        await asyncio.sleep(0.05)
        state = runtime._behavior_engine.face_state
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
