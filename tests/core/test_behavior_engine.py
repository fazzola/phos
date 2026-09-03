import asyncio

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
