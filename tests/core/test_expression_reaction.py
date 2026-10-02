from robot.core.expression_reaction import ExpressionReactionPolicy
from robot.vision.provider import ObservedExpression


def observation(label="happy", confidence=.9, available=True):
    return ObservedExpression(available, label if available else None,
                              confidence if available else None, "local", "FER+", 1.0)


def test_policy_requires_confidence_confirmation_and_cooldown():
    policy = ExpressionReactionPolicy(enabled=True, min_confidence=.7, confirmation_ms=500,
                                      cooldown_ms=2500, reaction_duration_ms=1200)
    assert policy.observe(observation(confidence=.6), now=0) is None
    assert policy.observe(observation(), now=1) is None
    assert policy.observe(observation(), now=1.4) is None
    intent = policy.observe(observation(), now=1.5)
    assert intent.reaction == "happy" and intent.duration_ms == 1200
    assert policy.observe(observation(), now=2) is None
    assert policy.observe(observation(), now=2.5) is None
    assert policy.observe(observation(), now=5) is None
    assert policy.observe(observation(), now=5.5) is not None


def test_policy_does_not_react_to_neutral_or_unavailable():
    policy = ExpressionReactionPolicy(enabled=True, min_confidence=.7, confirmation_ms=0,
                                      cooldown_ms=0, reaction_duration_ms=1200)
    assert policy.observe(observation("neutral"), now=0) is None
    assert policy.observe(observation(available=False), now=1) is None
