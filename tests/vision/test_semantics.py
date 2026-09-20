import math

import pytest

from robot.vision.provider import ExpressionObservation
from robot.vision.smoother import ExpressionSmoother


def observation(label="happy", confidence=0.9):
    return ExpressionObservation(label, confidence, ((label, confidence), ("other", 1 - confidence)))


@pytest.mark.parametrize("value,reason", [
    (None, "missing_prediction"),
    (ExpressionObservation("happy", 0.99), "missing_distribution"),
    (observation("neutral", 0.999), "neutral_not_calibrated"),
    (observation("happy", 0.79), "below_class_threshold"),
    (observation("surprise", 0.84), "below_class_threshold"),
    (observation("happy", 0.5), "below_class_threshold"),
    (observation("anger", 0.99), "unsupported_class"),
    (observation("fear", 0.99), "unsupported_class"),
    (observation("happy", math.nan), "invalid_distribution"),
    (observation("happy", math.inf), "invalid_distribution"),
    (observation("happy", 1.1), "invalid_distribution"),
    (ExpressionObservation("happy", 0.9, (("happy", 0.9), ("sad", 0.9))), "invalid_distribution"),
])
def test_abstains_without_positive_supported_evidence(value, reason):
    smoother = ExpressionSmoother()
    for timestamp in (0, 0.4, 0.8, 1.2):
        assert smoother.observe(value, timestamp=timestamp) is None
        assert smoother.decision.label == "unknown"
        assert smoother.decision.reason == reason
        assert smoother.temporal_state["count"] == 0


@pytest.mark.parametrize("label,confidence,duration,semantic", [
    ("happiness", 0.8, 0.8, "happy"),
    ("surprise", 0.85, 0.6, "surprised"),
    ("neutral", 0.95, 1.2, "neutral"),
])
def test_confirmed_semantics_require_count_and_duration(label, confidence, duration, semantic):
    smoother = ExpressionSmoother(neutral_enabled=True)
    value = observation(label, confidence)
    assert smoother.observe(value, timestamp=0) is None
    assert smoother.observe(value, timestamp=0.01) is None
    assert smoother.observe(value, timestamp=0.02) is None
    result = smoother.observe(value, timestamp=duration)
    assert result.label == semantic
    assert result.observed_for_ms == round(duration * 1000)
    assert smoother.decision.reason == "confirmed"


@pytest.mark.parametrize("interruption", [None, observation("happy", 0.6), observation("surprise")])
def test_missing_weak_or_conflicting_observation_breaks_confirmation(interruption):
    smoother = ExpressionSmoother()
    smoother.observe(observation(), timestamp=0)
    smoother.observe(observation(), timestamp=0.4)
    smoother.observe(interruption, timestamp=0.8)
    assert smoother.observe(observation(), timestamp=1.2) is None
    assert smoother.observe(observation(), timestamp=1.6) is None
    assert smoother.observe(observation(), timestamp=2.0).label == "happy"


def test_gaps_backwards_time_and_reset_discard_old_evidence():
    for next_time in (3.0, 0.4, 0.2):
        smoother = ExpressionSmoother()
        smoother.observe(observation(), timestamp=0)
        smoother.observe(observation(), timestamp=0.4)
        assert smoother.observe(observation(), timestamp=next_time) is None
        assert smoother.temporal_state["count"] == 1
        smoother.reset()
        assert smoother.observe(observation(), timestamp=next_time + 0.4) is None
        assert smoother.temporal_state["count"] == 1


def test_evidence_storage_is_bounded_during_long_sustained_expression():
    smoother = ExpressionSmoother()
    for i in range(10000):
        smoother.observe(observation(), timestamp=i * 0.4)
    assert smoother.temporal_state["count"] == 3
    assert smoother.decision.label == "happy"


@pytest.mark.parametrize("timestamp", [math.nan, math.inf, -math.inf])
def test_invalid_time_abstains_without_crashing(timestamp):
    smoother = ExpressionSmoother()
    assert smoother.observe(observation(), timestamp=timestamp) is None
    assert smoother.decision.reason == "invalid_timestamp"
