import asyncio

import pytest

from robot.core import BehaviorEngine, Event, EventBus, RobotState, STATE_CHANGED
from robot.ui import FaceExpression, VisualAccent


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


def test_behavior_engine_gives_stable_happy_and_surprised_observations_subtle_reactions():
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
    assert state.accent is VisualAccent.ALERT
    assert state.reaction_strength == pytest.approx(0.72)


def test_negative_visual_observations_do_not_select_an_expression():
    async def exercise():
        events = EventBus()
        engine = BehaviorEngine(events, blink_interval=(60, 60), gaze_interval=(60, 60))
        await engine.start()
        await events.publish(
            Event("vision.visual_expression_stable", {"visual_expression": {"label": "sad", "confidence": 0.95}})
        )
        state = engine.face_state
        await engine.stop()
        return state

    state = asyncio.run(exercise())
    assert state.expression is FaceExpression.NEUTRAL
    assert state.accent is VisualAccent.NEUTRAL
    assert state.reaction_strength == 0.0


def test_ferplus_model_labels_map_to_phos_behavior_semantics():
    async def exercise():
        events = EventBus()
        engine = BehaviorEngine(events, blink_interval=(60, 60), gaze_interval=(60, 60))
        await engine.start()
        await events.publish(
            Event("vision.visual_expression_stable", {"visual_expression": {"label": "happiness", "confidence": 0.9}})
        )
        happy = engine.face_state
        await events.publish(
            Event("vision.visual_expression_stable", {"visual_expression": {"label": "surprise", "confidence": 0.9}})
        )
        alert = engine.face_state
        await events.publish(
            Event("vision.visual_expression_stable", {"visual_expression": {"label": "contempt", "confidence": 0.9}})
        )
        attentive = engine.face_state
        await events.publish(
            Event("vision.visual_expression_stable", {"visual_expression": {"label": "neutral", "confidence": 0.9}})
        )
        neutral = engine.face_state
        await engine.stop()
        return happy, alert, attentive, neutral

    happy, alert, attentive, neutral = asyncio.run(exercise())
    assert happy.expression is FaceExpression.HAPPY
    assert happy.accent is VisualAccent.WARM
    assert alert.expression is FaceExpression.SURPRISED
    assert alert.accent is VisualAccent.ALERT
    assert attentive.expression is FaceExpression.SURPRISED
    assert attentive.accent is VisualAccent.ALERT
    assert neutral.expression is FaceExpression.NEUTRAL
    assert neutral.accent is VisualAccent.NEUTRAL


def test_visual_reactions_decay_smoothly_back_to_neutral():
    async def exercise():
        now = [0.0]
        events = EventBus()
        engine = BehaviorEngine(
            events,
            blink_interval=(60, 60),
            gaze_interval=(60, 60),
            reaction_decay_per_second=0.25,
            clock=lambda: now[0],
        )
        await engine.start()
        await events.publish(
            Event("vision.visual_expression_stable", {"visual_expression": {"label": "happy", "confidence": 1.0}})
        )
        now[0] = 1.0
        engine._decay_visual_reaction(now[0])
        fading = engine.face_state
        now[0] = 5.0
        engine._decay_visual_reaction(now[0])
        settled = engine.face_state
        await engine.stop()
        return fading, settled

    fading, settled = asyncio.run(exercise())
    assert fading.expression is FaceExpression.HAPPY
    assert fading.reaction_strength == pytest.approx(0.65)
    assert settled.expression is FaceExpression.NEUTRAL
    assert settled.accent is VisualAccent.NEUTRAL
    assert settled.reaction_strength == 0.0


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


def test_unknown_preserves_reaction_then_decays_without_changing_tracking():
    async def exercise():
        now = [0.0]
        engine = BehaviorEngine(EventBus(), clock=lambda: now[0])
        await engine._on_face_position(Event("", {"face_position": {"x": 0.5, "y": 0.5}}))
        await engine._on_visual_expression(Event("", {"visual_expression": {"label": "happy", "confidence": 0.9}}))
        before = engine.face_state
        await engine._on_visual_expression(Event("", {"visual_expression": {"label": "unknown", "confidence": 0.0}}))
        assert engine.face_state == before
        engine._decay_visual_reaction(4.0)
        assert engine.face_state.expression is FaceExpression.NEUTRAL
        assert engine.face_state.pupil_x == before.pupil_x
    asyncio.run(exercise())


def test_surprise_is_temporary_and_requires_confirmed_alternative_to_rearm():
    async def exercise():
        now = [0.0]
        engine = BehaviorEngine(EventBus(), clock=lambda: now[0])
        async def send(label):
            await engine._on_visual_expression(Event("", {"visual_expression": {"label": label, "confidence": 0.9}}))
        await send("surprised")
        for tick in range(1, 7):
            now[0] = float(tick)
            engine._decay_visual_reaction(now[0])
            await send("surprised")
        assert engine.face_state.expression is FaceExpression.NEUTRAL
        await send("unknown")
        await send("surprised")
        assert engine.face_state.expression is FaceExpression.NEUTRAL
        await send("happy")
        await send("surprised")
        assert engine.face_state.expression is FaceExpression.SURPRISED
        now[0] = 7.0
        await send("neutral")
        await send("surprised")
        assert engine.face_state.expression is FaceExpression.NEUTRAL  # cooldown
    asyncio.run(exercise())


@pytest.mark.parametrize("label,confidence", [([], 0.9), ("neutral", float("nan")), ("happy", 0)])
def test_invalid_events_do_not_rearm_surprise(label, confidence):
    async def exercise():
        engine = BehaviorEngine(EventBus())
        engine._surprise_armed = False
        await engine._on_visual_expression(Event("", {"visual_expression": {"label": label, "confidence": confidence}}))
        assert not engine._surprise_armed
    asyncio.run(exercise())
