import asyncio

import pytest

from robot.core import RobotState
from robot.runtime import RuntimeConfig, build_runtime
from robot.ui import FaceExpression, MemoryEyeDisplay
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
        FakeExpressionProvider(observation or ExpressionObservation("happy", 0.9)),
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


def test_stable_vision_observation_reaches_behavior_engine_and_renderer():
    async def exercise():
        display = MemoryEyeDisplay()
        runtime = build_runtime(
            eye_display=display,
            vision_factory=lambda events: make_vision(events, FakeCamera()),
        )
        await runtime.start()
        await asyncio.sleep(0.05)
        state = runtime._behavior_engine.face_state
        await runtime.stop()
        return state, display

    state, display = asyncio.run(exercise())
    assert state.expression is FaceExpression.HAPPY
    assert state.reaction_strength == 0.9
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
