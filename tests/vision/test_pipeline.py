import asyncio

from robot.core import EventBus
from robot.vision import (
    ExpressionObservation,
    ExpressionSmoother,
    FaceRegion,
    VisionPipeline,
    VisionStatus,
    VISION_EXPRESSION_STABLE,
    VISION_FACE_LOST,
)


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
        result = await pipeline.process_once(timestamp=0.0)
        return result, expressions

    result, expressions = asyncio.run(exercise())
    assert result.status is VisionStatus.UNSTABLE
    assert expressions.crops == [("crop", (slice(20, 110, None), slice(10, 110, None)))]


def test_low_confidence_observation_is_not_stable():
    async def exercise():
        pipeline = make_pipeline(
            FakeCamera(),
            FakeFaceDetector([FaceRegion(0, 0, 100, 100)]),
            FakeExpressionProvider([ExpressionObservation("happy", 0.4)]),
        )
        return await pipeline.process_once(timestamp=0.0)

    assert asyncio.run(exercise()).status is VisionStatus.LOW_CONFIDENCE


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


def test_stable_observation_is_published_once_as_visual_expression():
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
                    ExpressionObservation("happy", 0.7),
                    ExpressionObservation("happy", 0.9),
                ]
            ),
            events=events,
        )
        results = []
        for timestamp in (0.0, 0.2, 0.4, 0.6):
            results.append(await pipeline.process_once(timestamp=timestamp))
        return results, published

    results, published = asyncio.run(exercise())
    assert [result.status for result in results] == [
        VisionStatus.UNSTABLE,
        VisionStatus.UNSTABLE,
        VisionStatus.STABLE,
        VisionStatus.STABLE,
    ]
    assert published == [
        {
            "visual_expression": {
                "label": "happy",
                "confidence": 0.8,
                "observed_for_ms": 400,
            }
        }
    ]


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
