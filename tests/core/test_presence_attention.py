"""Lifecycle regressions for provider-neutral presence and attention semantics."""
import asyncio

from robot.core import Event
from robot.core.behavior_engine import BehaviorEngine
from robot.core.attention import (ATTENTION_TARGET_ACQUIRED, ATTENTION_TARGET_CHANGED,
                                  ATTENTION_TARGET_LOST, AttentionKind, AttentionManager)
from robot.core.events import EventBus
from robot.core.presence import (PERSON_ENTERED, PERSON_LEFT, PRESENCE_CHANGED,
                                 PresenceInterpreter, PresenceKind)
from robot.ui import FaceState, LEDRingSettings, VisualAccent
from robot.ui.led_ring import led_frame
from robot.ui.state import TransientVisualEffect


def test_presence_hysteresis_emits_each_lifecycle_event_once():
    async def scenario():
        events = EventBus()
        interpreter = PresenceInterpreter(events, enter_confirmation_seconds=.2, leave_confirmation_seconds=.3)
        emitted = []
        for name in (PERSON_ENTERED, PERSON_LEFT):
            events.subscribe(name, lambda event, name=name: emitted.append(name))

        candidate = {"id": "face-1", "type": "face", "x": .1, "y": -.1, "confidence": .82}
        await interpreter.observe(candidate, now=0.0)
        assert interpreter.state.state is PresenceKind.NO_ONE
        await interpreter.observe(candidate, now=.2)
        assert interpreter.state.state is PresenceKind.PERSON_PRESENT
        await interpreter.observe(candidate, now=.3)
        await interpreter.observe(None, now=.4)  # shorter than leave confirmation
        assert interpreter.state.state is PresenceKind.PERSON_PRESENT
        await interpreter.observe(None, now=.6)
        assert interpreter.state.state is PresenceKind.NO_ONE
        await interpreter.observe(None, now=1.0)
        assert emitted == [PERSON_ENTERED, PERSON_LEFT]

    asyncio.run(scenario())


def test_attention_acquires_changes_loses_and_holds_target_once():
    async def scenario():
        events = EventBus()
        manager = AttentionManager(events, lost_hold_seconds=.4)
        emitted = []
        for name in (ATTENTION_TARGET_ACQUIRED, ATTENTION_TARGET_CHANGED, ATTENTION_TARGET_LOST):
            events.subscribe(name, lambda event, name=name: emitted.append((name, dict(event.data))))
        await manager.start()
        await events.publish(Event(PRESENCE_CHANGED, {"state": "person_present"}))
        first = {"id": "face-1", "x": .2, "y": -.2, "confidence": .82}
        await manager.observe(first, now=0.0)
        assert manager.state.state is AttentionKind.ACQUIRING
        await manager.observe(first, now=.1)
        assert manager.state.state is AttentionKind.TRACKING
        await manager.observe(first, now=.2)
        await manager.observe({**first, "id": "face-2"}, now=.3)
        await events.publish(Event(PRESENCE_CHANGED, {"state": "no_one"}))
        assert manager.state.state is AttentionKind.LOST
        await manager.observe(None, now=.6)
        assert manager.state.state is AttentionKind.LOST
        await manager.observe(None, now=.71)
        assert manager.state.state is AttentionKind.IDLE
        assert [name for name, _ in emitted] == [ATTENTION_TARGET_ACQUIRED, ATTENTION_TARGET_CHANGED, ATTENTION_TARGET_LOST]
        assert emitted[1][1]["old_target_id"] == "face-1"
        assert emitted[1][1]["new_target_id"] == "face-2"
        await manager.stop()

    asyncio.run(scenario())


def test_attention_failed_acquisition_returns_to_idle_without_acquired_event():
    async def scenario():
        events = EventBus()
        manager = AttentionManager(events, lost_hold_seconds=.1)
        acquired = []
        events.subscribe(ATTENTION_TARGET_ACQUIRED, acquired.append)
        await manager.start()
        await events.publish(Event(PRESENCE_CHANGED, {"state": "person_present"}))
        await manager.observe({"id": "face-1", "x": 0.0, "y": 0.0, "confidence": None}, now=0.0)
        assert manager.state.state is AttentionKind.ACQUIRING
        await manager.observe(None, now=.1)
        assert manager.state.state is AttentionKind.IDLE
        assert acquired == []
        await manager.stop()

    asyncio.run(scenario())


def test_presence_led_effect_uses_configured_intent_and_then_resolves_current_state():
    async def scenario():
        now = [10.0]
        engine = BehaviorEngine(EventBus(), presence_led_reactions_enabled=True,
                                presence_led_entered_duration_seconds=.5,
                                presence_led_left_duration_seconds=.6,
                                presence_led_entered_direction="counter_clockwise",
                                presence_led_left_direction="clockwise", clock=lambda: now[0])
        await engine._on_presence_event(Event(PERSON_ENTERED))
        entered = engine.face_state
        assert (entered.transient_effect, entered.transient_effect_duration_seconds,
                entered.transient_effect_direction) == (TransientVisualEffect.PRESENCE_ENTERED, .5, "counter_clockwise")
        settings = LEDRingSettings(True, 4, 18, .3, "cyan", True, 30)
        active = led_frame(entered, settings, now[0] + .2)
        assert active.effect == "presence_entered"
        # A persistent state established during the transient is what is seen
        # once it expires; no pre-effect LED frame is cached for restoration.
        engine._state = FaceState(accent=VisualAccent.WARM, transient_effect=entered.transient_effect,
                                  transient_effect_started_at=entered.transient_effect_started_at,
                                  transient_effect_duration_seconds=entered.transient_effect_duration_seconds,
                                  transient_effect_direction=entered.transient_effect_direction)
        restored = led_frame(engine.face_state, settings, now[0] + .6)
        assert restored.effect == "pulse" and restored.semantic_state == "warm"
        await engine._on_presence_event(Event(PERSON_LEFT))
        assert engine.face_state.transient_effect_direction == "clockwise"
        assert engine.face_state.transient_effect_duration_seconds == .6

    asyncio.run(scenario())
