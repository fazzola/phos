import asyncio
import logging

from robot.core import EventBus
from robot.vision import (
    ExpressionObservation as RawObservation,
    ExpressionSmoother,
    FaceRegion,
    VisionPipeline,
    VisionStatus,
    VISION_EXPRESSION_STABLE,
    VISION_FACE_LOST,
    VISION_FACE_POSITION,
)


def ExpressionObservation(label, confidence):
    return RawObservation(label, confidence, ((label, confidence), ("other", 1 - confidence)))


class FakeFrame:
    shape = (480, 640, 3)

    def __getitem__(self, item):
        return ("crop", item)


class FakeCamera:
    def __init__(self):
        self.captures = 0
        self.started = False
        self.stopped = False

    async def start(self):
        self.started = True

    async def capture_frame(self):
        self.captures += 1
        return FakeFrame()

    async def stop(self):
        self.stopped = True


class FakeFaceDetector:
    def __init__(self, faces):
        self.faces = list(faces)
        self.calls = 0

    async def detect(self, frame):
        self.calls += 1
        return self.faces


class FakeExpressionProvider:
    def __init__(self, observations):
        self.observations = list(observations)
        self.crops = []

    async def classify(self, face_crop):
        self.crops.append(face_crop)
        return self.observations.pop(0) if self.observations else None


def make_pipeline(camera, detector, expressions, *, events=None, smoother=None):
    return VisionPipeline(
        camera,
        detector,
        expressions,
        smoother or ExpressionSmoother(minimum_observations=3),
        events=events,
        detection_interval_seconds=0.1,
        expression_interval_seconds=0.1,
    )


def test_no_face_does_not_call_expression_provider():
    async def exercise():
        expressions = FakeExpressionProvider([])
        pipeline = make_pipeline(FakeCamera(), FakeFaceDetector([]), expressions)
        result = await pipeline.process_once(timestamp=0.0)
        return result, expressions

    result, expressions = asyncio.run(exercise())
    assert result.status is VisionStatus.NO_FACE
    assert expressions.crops == []


def test_largest_face_is_cropped_for_expression_inference():
    async def exercise():
        expressions = FakeExpressionProvider([ExpressionObservation("happy", 0.9)])
        pipeline = make_pipeline(
            FakeCamera(),
            FakeFaceDetector([FaceRegion(2, 3, 30, 30), FaceRegion(10, 20, 100, 90)]),
            expressions,
        )
        await pipeline.process_once(timestamp=0.0)
        assert expressions.crops == []  # reject one-frame acquisitions for FER
        result = await pipeline.process_once(timestamp=0.2)
        return result, expressions

    result, expressions = asyncio.run(exercise())
    assert result.status is VisionStatus.UNSTABLE
    assert expressions.crops == [("crop", (slice(5, 125, None), slice(0, 120, None)))]


def test_low_confidence_observation_is_not_stable():
    async def exercise():
        pipeline = make_pipeline(
            FakeCamera(),
            FakeFaceDetector([FaceRegion(0, 0, 100, 100)]),
            FakeExpressionProvider([ExpressionObservation("happy", 0.4)]),
        )
        await pipeline.process_once(timestamp=0.0)
        return await pipeline.process_once(timestamp=0.2)

    assert asyncio.run(exercise()).status is VisionStatus.UNKNOWN


def test_face_lost_is_published_after_a_previously_detected_face():
    async def exercise():
        events = EventBus()
        published = []
        events.subscribe(VISION_FACE_LOST, lambda event: published.append(event.name))
        detector = FakeFaceDetector([FaceRegion(0, 0, 100, 100)])
        pipeline = make_pipeline(
            FakeCamera(), detector, FakeExpressionProvider([ExpressionObservation("neutral", 0.9)]), events=events
        )
        await pipeline.process_once(timestamp=0.0)
        detector.faces = []
        result = await pipeline.process_once(timestamp=0.2)
        return result, published

    result, published = asyncio.run(exercise())
    assert result.status is VisionStatus.NO_FACE
    assert published == [VISION_FACE_LOST]


def test_detected_face_position_is_published_without_expression_configuration():
    async def exercise():
        events = EventBus()
        published = []
        events.subscribe(VISION_FACE_POSITION, lambda event: published.append(event.data))
        pipeline = VisionPipeline(
            FakeCamera(),
            FakeFaceDetector([FaceRegion(400, 120, 80, 120)]),
            None,
            None,
            events=events,
        )
        result = await pipeline.process_once(timestamp=0.0)
        return result, published

    result, published = asyncio.run(exercise())
    assert result.status is VisionStatus.FACE_DETECTED
    assert published == [{"face_position": {"x": 0.375, "y": -0.25}}]


def test_smoother_requires_consistent_timely_observations():
    smoother = ExpressionSmoother(minimum_observations=3, maximum_gap_seconds=1.0)
    observation = ExpressionObservation("happy", 0.8)

    assert smoother.observe(observation, timestamp=0.0) is None
    assert smoother.observe(observation, timestamp=0.3) is None
    stable = smoother.observe(observation, timestamp=0.8)

    assert stable is not None
    assert stable.label == "happy"
    assert stable.confidence == 0.8
    assert stable.observed_for_ms == 800


def test_each_stable_observation_is_published_to_refresh_the_behavior_reaction():
    async def exercise():
        events = EventBus()
        published = []
        events.subscribe(VISION_EXPRESSION_STABLE, lambda event: published.append(event.data))
        pipeline = make_pipeline(
            FakeCamera(),
            FakeFaceDetector([FaceRegion(0, 0, 100, 100)]),
            FakeExpressionProvider(
                [
                    ExpressionObservation("happy", 0.8),
                    ExpressionObservation("happy", 0.9),
                    ExpressionObservation("happy", 0.8),
                    ExpressionObservation("happy", 0.9),
                ]
            ),
            events=events,
        )
        await pipeline.process_once(timestamp=0.0)  # acquisition, gaze only
        results = []
        for timestamp in (0.2, 0.6, 1.0, 1.4):
            results.append(await pipeline.process_once(timestamp=timestamp))
        return results, published

    results, published = asyncio.run(exercise())
    assert [result.status for result in results] == [
        VisionStatus.UNSTABLE,
        VisionStatus.UNSTABLE,
        VisionStatus.STABLE,
        VisionStatus.STABLE,
    ]
    assert [item["visual_expression"]["label"] for item in published[:2]] == ["unknown", "unknown"]
    assert published[2:] == [
        {
            "visual_expression": {
                "label": "happy",
                "confidence": 0.833333,
                "observed_for_ms": 800,
            }
        },
        {
            "visual_expression": {
                "label": "happy",
                "confidence": 0.866667,
                "observed_for_ms": 1200,
            }
        },
    ]


def test_expression_observation_is_logged_before_it_becomes_stable(caplog):
    async def exercise():
        pipeline = make_pipeline(
            FakeCamera(),
            FakeFaceDetector([FaceRegion(0, 0, 100, 100)]),
            FakeExpressionProvider(
                [
                    ExpressionObservation("happiness", 0.9),
                    ExpressionObservation("happiness", 0.9),
                    ExpressionObservation("happiness", 0.9),
                    ExpressionObservation("happiness", 0.9),
                ]
            ),
        )
        for timestamp in (0.0, 0.2, 0.4, 0.6):
            await pipeline.process_once(timestamp=timestamp)

    with caplog.at_level(logging.INFO, logger="robot.vision.pipeline"):
        asyncio.run(exercise())

    assert caplog.messages == ["Visible expression observation: happiness (confidence 0.90)"]


def test_detection_is_rate_limited_while_frames_are_captured():
    async def exercise():
        camera = FakeCamera()
        detector = FakeFaceDetector([])
        pipeline = make_pipeline(camera, detector, FakeExpressionProvider([]))
        first = await pipeline.process_once(timestamp=0.0)
        second = await pipeline.process_once(timestamp=0.05)
        return first, second, camera.captures, detector.calls

    first, second, captures, detector_calls = asyncio.run(exercise())
    assert first.status is VisionStatus.NO_FACE
    assert second.status is VisionStatus.NOT_DUE
    assert captures == 2
    assert detector_calls == 1


def test_unknown_is_published_with_diagnostics_while_tracking_continues(caplog):
    async def exercise():
        events = EventBus()
        semantic = []
        positions = []
        events.subscribe(VISION_EXPRESSION_STABLE, lambda event: semantic.append(event.data))
        events.subscribe(VISION_FACE_POSITION, lambda event: positions.append(event.data))
        pipeline = make_pipeline(
            FakeCamera(), FakeFaceDetector([FaceRegion(0, 0, 100, 100)]),
            FakeExpressionProvider([ExpressionObservation("neutral", 0.99), None]), events=events,
        )
        pipeline._diagnostics = True
        await pipeline.process_once(timestamp=0.0)
        for timestamp in (0.4, 0.8):
            result = await pipeline.process_once(timestamp=timestamp)
            assert result.status is VisionStatus.UNKNOWN
            assert result.visual_expression.label == "unknown"
        assert len(positions) == 3
        assert [item["visual_expression"]["label"] for item in semantic] == ["unknown", "unknown"]
    with caplog.at_level(logging.INFO, logger="robot.vision.pipeline"):
        asyncio.run(exercise())
    assert any("reason=neutral_not_calibrated" in message for message in caplog.messages)
    assert any("reason=missing_prediction" in message for message in caplog.messages)
    assert any("top=[('neutral', 0.99)" in message and "temporal=" in message for message in caplog.messages)


def test_face_loss_discards_partial_expression_confirmation():
    async def exercise():
        detector = FakeFaceDetector([FaceRegion(0, 0, 100, 100)])
        pipeline = make_pipeline(FakeCamera(), detector,
                                 FakeExpressionProvider([ExpressionObservation("happy", 0.9)] * 5))
        await pipeline.process_once(timestamp=0)
        await pipeline.process_once(timestamp=0.4)
        detector.faces = []
        assert (await pipeline.process_once(timestamp=0.8)).status is VisionStatus.NO_FACE
        detector.faces = [FaceRegion(0, 0, 100, 100)]
        assert (await pipeline.process_once(timestamp=1.2)).status is VisionStatus.UNSTABLE
        assert (await pipeline.process_once(timestamp=1.6)).status is VisionStatus.UNSTABLE
        assert (await pipeline.process_once(timestamp=2.0)).status is VisionStatus.UNSTABLE
        assert (await pipeline.process_once(timestamp=2.4)).status is VisionStatus.STABLE
    asyncio.run(exercise())


def test_jump_does_not_reach_classifier_or_gaze_and_diagnostics_explain_rejection(caplog):
    async def exercise():
        events = EventBus()
        positions, lost = [], []
        events.subscribe(VISION_FACE_POSITION, lambda event: positions.append(event.data))
        events.subscribe(VISION_FACE_LOST, lambda event: lost.append(event))
        face = FaceRegion(100, 100, 100, 100)
        jump = FaceRegion(420, 300, 100, 100)
        detector = FakeFaceDetector([face])
        provider = FakeExpressionProvider([ExpressionObservation('happy', 0.9)] * 4)
        pipeline = make_pipeline(FakeCamera(), detector, provider, events=events)
        pipeline._diagnostics = True
        await pipeline.process_once(timestamp=0)
        await pipeline.process_once(timestamp=0.2)
        assert len(provider.crops) == 1
        detector.faces = [jump]
        assert (await pipeline.process_once(timestamp=0.4)).status is VisionStatus.NO_FACE
        assert len(provider.crops) == 1
        assert len(positions) == 2
        assert len(lost) == 1
        detector.faces = [jump, face]
        await pipeline.process_once(timestamp=0.6)
        assert len(provider.crops) == 1  # a missed detection breaks confirmation
        await pipeline.process_once(timestamp=0.8)
        assert len(provider.crops) == 2
        assert positions[-1] == positions[0]
    with caplog.at_level(logging.INFO, logger='robot.vision.pipeline'):
        asyncio.run(exercise())
    assert any('position_jump' in message and 'selected=None' in message for message in caplog.messages)
    assert any('reason=continuity_match' in message for message in caplog.messages)
    assert any('Face crop: region=' in message for message in caplog.messages)


def test_new_track_after_long_pause_cannot_inherit_expression_confirmation():
    async def exercise():
        detector = FakeFaceDetector([FaceRegion(100, 100, 100, 100)])
        provider = FakeExpressionProvider([ExpressionObservation('happy', 0.9)] * 5)
        pipeline = make_pipeline(FakeCamera(), detector, provider)
        for timestamp in (0, 0.2, 0.6, 1.0):
            result = await pipeline.process_once(timestamp=timestamp)
        assert result.status is VisionStatus.STABLE
        detector.faces = [FaceRegion(420, 300, 100, 100)]
        result = await pipeline.process_once(timestamp=2.2)
        assert result.status is VisionStatus.UNSTABLE
        assert len(provider.crops) == 3
        assert (await pipeline.process_once(timestamp=2.4)).status is VisionStatus.UNSTABLE
    asyncio.run(exercise())
