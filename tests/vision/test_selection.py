import pytest

from robot.vision.provider import FaceRegion
from robot.vision.selection import FaceSelector
from robot.vision.pipeline import crop_face, square_face_region


class Frame:
    shape = (480, 640, 3)

    def __getitem__(self, item):
        return item


def select(selector, boxes, timestamp):
    return selector.select(boxes, width=640, height=480, timestamp=timestamp)


def test_larger_competitor_and_order_do_not_replace_tracked_face():
    selector = FaceSelector()
    original = FaceRegion(100, 100, 100, 100)
    competitor = FaceRegion(370, 100, 150, 150)
    assert not select(selector, [original], 0).expression_ready
    for index, boxes in enumerate(([competitor, original], [original, competitor]), start=1):
        result = select(selector, boxes, index * 0.25)
        assert result.face == original
        assert result.expression_ready
        assert result.reason == 'continuity_match'
        assert (competitor, 'position_jump') in result.rejected


def test_best_overlap_wins_among_plausible_candidates():
    selector = FaceSelector()
    original = FaceRegion(100, 100, 100, 100)
    select(selector, [original], 0)
    near = FaceRegion(103, 100, 102, 100)
    competitor = FaceRegion(140, 100, 120, 120)
    result = select(selector, [competitor, near], 0.25)
    assert result.face == near
    assert (competitor, 'competing_detection') in result.rejected


@pytest.mark.parametrize('jump,reason', [
    (FaceRegion(400, 100, 100, 100), 'position_jump'),
    (FaceRegion(50, 50, 200, 200), 'size_jump'),
    (FaceRegion(120, 120, 40, 40), 'size_jump'),
])
def test_jumps_are_rejected_without_advancing_or_poisoning_track(jump, reason):
    selector = FaceSelector()
    original = FaceRegion(100, 100, 100, 100)
    select(selector, [original], 0)
    result = select(selector, [jump], 0.25)
    assert result.face is None
    assert (jump, reason) in result.rejected
    result = select(selector, [original], 0.5)
    assert result.face == original
    assert not result.expression_ready
    assert select(selector, [original], 0.75).expression_ready


def test_rejected_detections_do_not_prevent_expiry_and_reacquisition():
    selector = FaceSelector()
    original = FaceRegion(100, 100, 100, 100)
    other = FaceRegion(400, 100, 100, 100)
    select(selector, [original], 0)
    for timestamp in (0.25, 0.5, 1.0):
        assert select(selector, [other], timestamp).face is None
    result = select(selector, [other], 1.25)
    assert result.face == other
    assert result.new_track
    assert not result.expression_ready
    assert select(selector, [other], 1.5).expression_ready


def test_dropout_never_returns_stale_box_and_requires_reconfirmation():
    selector = FaceSelector()
    original = FaceRegion(100, 100, 100, 100)
    select(selector, [original], 0)
    assert select(selector, [original], 0.25).expression_ready
    assert select(selector, [], 0.5).face is None
    assert not select(selector, [original], 0.75).expression_ready
    assert select(selector, [original], 1.0).expression_ready


def test_gradual_motion_keeps_gaze_unsmoothed_and_damps_crop_size_jitter():
    selector = FaceSelector()
    select(selector, [FaceRegion(100, 100, 100, 100)], 0)
    moved = FaceRegion(110, 105, 110, 110)
    result = select(selector, [moved], 0.25)
    assert result.face == moved
    assert result.crop_size == 105
    assert square_face_region(Frame(), moved, reference_size=result.crop_size).width == 126


def test_frame_size_change_resets_continuity():
    selector = FaceSelector()
    box = FaceRegion(100, 100, 100, 100)
    select(selector, [box], 0)
    select(selector, [box], 0.25)
    result = selector.select([box], width=800, height=600, timestamp=0.5)
    assert result.new_track
    assert not result.expression_ready


@pytest.mark.parametrize('box', [FaceRegion(-1, 0, 100, 100), FaceRegion(0, 0, 0, 30),
                                  FaceRegion(600, 0, 100, 100), FaceRegion(0, 0, 100, 10)])
def test_invalid_and_implausible_boxes_are_not_selected(box):
    result = select(FaceSelector(), [box], 0)
    assert result.face is None
    assert result.rejected[0][0] == box


@pytest.mark.parametrize('box', [FaceRegion(0, 0, 80, 100), FaceRegion(560, 0, 80, 100),
                                  FaceRegion(0, 380, 80, 100), FaceRegion(560, 380, 80, 100),
                                  FaceRegion(100, 100, 100, 80), FaceRegion(50, 0, 480, 480)])
def test_square_crop_stays_inside_frame_and_contains_face_at_edges(box):
    region = square_face_region(Frame(), box)
    assert region.width == region.height
    assert 0 <= region.x <= box.x
    assert 0 <= region.y <= box.y
    assert box.x + box.width <= region.x + region.width <= 640
    assert box.y + box.height <= region.y + region.height <= 480
    assert crop_face(Frame(), box) == (slice(region.y, region.y + region.height),
                                     slice(region.x, region.x + region.width))


def test_crop_margin_is_configurable_without_changing_detected_face():
    box = FaceRegion(100, 100, 100, 80)
    assert square_face_region(Frame(), box, margin=0).width == 100
    assert square_face_region(Frame(), box, margin=0.2).width == 140
    assert square_face_region(Frame(), box, reference_size=50).width == 100


@pytest.mark.parametrize('margin', [-0.1, 0.6, float('inf'), float('nan')])
def test_invalid_crop_margin_is_rejected(margin):
    with pytest.raises(ValueError):
        crop_face(Frame(), FaceRegion(0, 0, 100, 100), margin=margin)


def test_invisible_or_uncontainable_faces_do_not_create_crops():
    assert crop_face(Frame(), FaceRegion(700, 100, 100, 100)) is None
    assert crop_face(Frame(), FaceRegion(0, 0, 640, 480)) is None
