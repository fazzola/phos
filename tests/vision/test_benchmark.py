import asyncio

from robot.vision.benchmark import compare_crop, summarize
from robot.vision.provider import ExpressionObservation
from robot.vision.smoother import ExpressionSmoother


class Provider:
    last_inference_ms = 10.0

    def __init__(self, label):
        self.label = label
        self.crops = []

    async def classify(self, crop):
        self.crops.append(crop)
        return ExpressionObservation(self.label, 0.9, ((self.label, 0.9), ("neutral", 0.1)))


def test_comparison_uses_identical_crops_and_resets_stability_when_face_lost():
    async def exercise():
        providers = {"ferplus": Provider("happiness"), "mobilefacenet": Provider("happy")}
        smoothers = {name: ExpressionSmoother() for name in providers}
        crop = object()
        for index in range(3):
            rows = await compare_crop(crop, providers, smoothers, timestamp=index * 0.4,
                                      reverse=bool(index % 2))
        assert {row["semantic"] for row in rows} == {"happy"}
        assert all(row["stable_label"] for row in rows)
        assert all(all(item is crop for item in provider.crops) for provider in providers.values())
        missing = await compare_crop(None, providers, smoothers, timestamp=1.2)
        assert all(row["label"] is None for row in missing)
        rows = await compare_crop(crop, providers, smoothers, timestamp=1.6)
        assert all(row["stable_label"] is None for row in rows)
    asyncio.run(exercise())


def test_summary_counts_neutral_bias_and_does_not_treat_missing_faces_as_predictions():
    rows = [dict(label=label, semantic=label, expected="happy", confidence=0.9,
                 stable_label=label if index == 0 else None, inference_ms=index + 1,
                 classify_ms=5) for index, label in enumerate(("neutral", "happy", None, "neutral"))]
    summary = summarize(rows)
    assert summary["face_samples"] == 3
    assert summary["neutral_fraction"] == 2 / 3
    assert summary["semantic_agreement"] == 1 / 3
    assert summary["label_switches"] == 1
    assert summary["adjacent_pairs"] == 1
    assert summary["stable_fraction"] == 1 / 4
    assert summary["inference_p95_ms"] == 4
    assert summarize([]) == {"samples": 0, "face_samples": 0}
