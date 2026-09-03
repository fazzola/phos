import asyncio

import pytest

from robot.core import BehaviorEngine, Event, EventBus, RobotState, STATE_CHANGED
from robot.ui import FaceExpression


def test_behavior_engine_maps_core_state_to_face_state():
    async def exercise():
        events = EventBus()
        engine = BehaviorEngine(events, blink_interval=(60, 60), gaze_interval=(60, 60))
        await engine.start()
        await events.publish(Event(STATE_CHANGED, {"current": RobotState.SLEEPING.value}))
        state = engine.face_state
        await engine.stop()
        return state

    state = asyncio.run(exercise())
    assert state.expression is FaceExpression.SLEEPY
    assert state.reaction_strength == 1.0


def test_behavior_engine_uses_visual_expression_confidence_as_reaction_strength():
    async def exercise():
        events = EventBus()
        engine = BehaviorEngine(events, blink_interval=(60, 60), gaze_interval=(60, 60))
        await engine.start()
        await events.publish(
            Event("vision.visual_expression_stable", {"visual_expression": {"label": "surprised", "confidence": 0.72}})
        )
        state = engine.face_state
        await engine.stop()
        return state

    state = asyncio.run(exercise())
    assert state.expression is FaceExpression.SURPRISED
    assert state.reaction_strength == 0.72


def test_non_idle_robot_state_overrides_visual_expression_reaction():
    async def exercise():
        events = EventBus()
        engine = BehaviorEngine(events, blink_interval=(60, 60), gaze_interval=(60, 60))
        await engine.start()
        await events.publish(Event(STATE_CHANGED, {"current": RobotState.SPEAKING.value}))
        await events.publish(
            Event("vision.visual_expression_stable", {"visual_expression": {"label": "surprised", "confidence": 0.9}})
        )
        state = engine.face_state
        await engine.stop()
        return state

    state = asyncio.run(exercise())
    assert state.expression is FaceExpression.HAPPY


def test_behavior_engine_smooths_face_position_and_resets_gaze_on_face_loss():
    async def exercise():
        events = EventBus()
        engine = BehaviorEngine(events, blink_interval=(60, 60), gaze_interval=(60, 60))
        await engine.start()
        await events.publish(Event("vision.face_position", {"face_position": {"x": 1.0, "y": -1.0}}))
        first = engine.face_state
        await events.publish(Event("vision.face_position", {"face_position": {"x": 1.0, "y": -1.0}}))
        second = engine.face_state
        await events.publish(Event("vision.face_lost"))
        lost = engine.face_state
        await engine.stop()
        return first, second, lost

    first, second, lost = asyncio.run(exercise())
    assert (first.pupil_x, first.pupil_y) == pytest.approx((0.2275, -0.1575))
    assert first.pupil_x < second.pupil_x < 0.65
    assert first.pupil_y > second.pupil_y > -0.45
    assert (lost.pupil_x, lost.pupil_y) == (0.0, 0.0)


def test_non_idle_robot_state_overrides_face_position_tracking():
    async def exercise():
        events = EventBus()
        engine = BehaviorEngine(events, blink_interval=(60, 60), gaze_interval=(60, 60))
        await engine.start()
        await events.publish(Event(STATE_CHANGED, {"current": RobotState.SLEEPING.value}))
        await events.publish(Event("vision.face_position", {"face_position": {"x": 1.0, "y": 1.0}}))
        state = engine.face_state
        await engine.stop()
        return state

    state = asyncio.run(exercise())
    assert state.expression is FaceExpression.SLEEPY
    assert (state.pupil_x, state.pupil_y) == (0.0, 0.0)
