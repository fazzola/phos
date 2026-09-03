from robot.ui import BlinkPhase, EyeRenderer, FaceExpression, FaceState


def render(state, timestamp=0.0):
    return EyeRenderer().render(state, timestamp=timestamp)


def test_neutral_state_renders_two_open_centered_eyes():
    frame = render(FaceState())

    assert frame.width == 800
    assert frame.height == 600
    assert frame.eyes[0].center_x < 400 < frame.eyes[1].center_x
    assert all(eye.radius_y > 100 for eye in frame.eyes)


def test_expression_transition_interpolates_eye_shape_and_gaze():
    renderer = EyeRenderer(transition_seconds=0.2)
    renderer.render(FaceState(), timestamp=0.0)
    partial = renderer.render(
        FaceState(expression=FaceExpression.HAPPY, reaction_strength=1.0, pupil_x=0.8), timestamp=0.1
    )
    completed = renderer.render(
        FaceState(expression=FaceExpression.HAPPY, reaction_strength=1.0, pupil_x=0.8), timestamp=0.3
    )

    assert partial.eyes[0].radius_y > completed.eyes[0].radius_y
    assert partial.eyes[0].pupil_x < completed.eyes[0].pupil_x


def test_pupil_coordinates_are_clamped_inside_eye_geometry():
    frame = render(FaceState(pupil_x=99, pupil_y=-99))
    for eye in frame.eyes:
        assert abs(eye.pupil_x - eye.center_x) + eye.pupil_radius < eye.radius_x
        assert abs(eye.pupil_y - eye.center_y) + eye.pupil_radius < eye.radius_y


def test_blink_phase_controls_aperture_without_interpolation_delay():
    renderer = EyeRenderer()
    renderer.render(FaceState(), timestamp=0.0)
    closing = renderer.render(FaceState(blink_phase=BlinkPhase.CLOSING, blink_progress=0.5), timestamp=0.01)
    closed = renderer.render(FaceState(blink_phase=BlinkPhase.CLOSED), timestamp=0.02)

    assert closing.eyes[0].radius_y < 100
    assert closed.eyes[0].closed


def test_reaction_strength_zero_keeps_neutral_geometry():
    neutral = render(FaceState())
    dormant_happy = render(FaceState(expression=FaceExpression.HAPPY, reaction_strength=0.0))

    assert neutral.eyes[0].radius_y == dormant_happy.eyes[0].radius_y


def test_sleepy_expression_has_significantly_smaller_aperture():
    neutral = render(FaceState())
    sleepy = render(FaceState(expression=FaceExpression.SLEEPY, reaction_strength=1.0))

    assert sleepy.eyes[0].radius_y < neutral.eyes[0].radius_y * 0.5


def test_invalid_face_state_values_are_safely_normalized():
    state = FaceState(
        background="not-a-colour",
        eye_open=100,
        squint=-2,
        pupil_x=4,
        pupil_y=-4,
        reaction_strength=4,
        blink_progress=-1,
    ).normalized()

    assert state.background == "#10243A"
    assert state.eye_open == 1.25
    assert state.squint == 0.0
    assert state.pupil_x == 1.0
    assert state.pupil_y == -1.0
    assert state.reaction_strength == 1.0
    assert state.blink_progress == 0.0
