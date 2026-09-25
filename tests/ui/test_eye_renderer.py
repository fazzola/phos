from types import SimpleNamespace

from robot.ui import BlinkPhase, EyeRenderer, FaceExpression, FaceState, TkEyeDisplay, VisualAccent


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


def test_semantic_accent_changes_eye_and_pupil_colors():
    neutral = render(FaceState())
    warm = render(FaceState(accent=VisualAccent.WARM, reaction_strength=1.0))
    alert = render(FaceState(accent=VisualAccent.ALERT, reaction_strength=1.0))

    assert neutral.eye_color == "#EAFBFF"
    assert warm.eye_color == "#28E0B0"
    assert warm.pupil_color == "#063B3D"
    assert alert.eye_color == "#FFC857"
    assert alert.eye_color != warm.eye_color


def test_accent_and_background_colors_interpolate_smoothly():
    renderer = EyeRenderer(transition_seconds=0.2)
    neutral = renderer.render(FaceState(), timestamp=0.0)
    partial = renderer.render(
        FaceState(background="#08101E", accent=VisualAccent.SLEEPY, reaction_strength=1.0), timestamp=0.1
    )
    completed = renderer.render(
        FaceState(background="#08101E", accent=VisualAccent.SLEEPY, reaction_strength=1.0), timestamp=0.3
    )

    assert neutral.eye_color != partial.eye_color != completed.eye_color
    assert neutral.background != partial.background != completed.background
    assert completed.eye_color == "#A78BFA"


def test_sleepy_expression_has_significantly_smaller_aperture():
    neutral = render(FaceState())
    sleepy = render(FaceState(expression=FaceExpression.SLEEPY, reaction_strength=1.0))

    assert sleepy.eyes[0].radius_y < neutral.eyes[0].radius_y * 0.5


def test_invalid_face_state_values_are_safely_normalized():
    state = FaceState(
        background="not-a-colour",
        eye_open=100,
        eye_asymmetry=100,
        squint=-2,
        pupil_x=4,
        pupil_y=-4,
        reaction_strength=4,
        accent="not-an-accent",
        blink_progress=-1,
    ).normalized()

    assert state.background == "#10243A"
    assert state.eye_open == 1.25
    assert state.eye_asymmetry == .5
    assert state.squint == 0.0
    assert state.pupil_x == 1.0
    assert state.pupil_y == -1.0
    assert state.reaction_strength == 1.0
    assert state.accent is VisualAccent.NEUTRAL
    assert state.blink_progress == 0.0


def test_configured_iris_theme_changes_stylized_iris_color():
    cyan = EyeRenderer(iris_color="cyan").render(FaceState(), timestamp=0)
    violet = EyeRenderer(iris_color="violet").render(FaceState(), timestamp=0)

    assert cyan.iris_color == "#28CEEB"
    assert violet.iris_color == "#A670F5"
    assert cyan.eyes[0].iris_radius > cyan.eyes[0].pupil_radius


def test_semantic_iris_tint_interpolates_from_face_state():
    renderer = EyeRenderer(iris_color="blue", transition_seconds=.2)
    neutral = renderer.render(FaceState(), timestamp=0)
    partial = renderer.render(
        FaceState(accent=VisualAccent.ALERT, reaction_strength=1), timestamp=.1
    )
    settled = renderer.render(
        FaceState(accent=VisualAccent.ALERT, reaction_strength=1), timestamp=.3
    )

    assert neutral.iris_color != partial.iris_color != settled.iris_color
    assert settled.iris_color != "#A670F5"


def test_expression_states_remain_face_state_driven():
    renderer = EyeRenderer()
    neutral = renderer.render(FaceState(), timestamp=0)
    curious = renderer.render(
        FaceState(expression=FaceExpression.CURIOUS, reaction_strength=1), timestamp=1
    )
    surprised = renderer.render(
        FaceState(expression=FaceExpression.SURPRISED, reaction_strength=1), timestamp=2
    )

    assert curious.eyes[0].radius_y != curious.eyes[1].radius_y
    assert surprised.eyes[0].radius_y > neutral.eyes[0].radius_y


def test_explicit_eye_asymmetry_mirrors_eyes_and_overrides_expression_bias():
    left = render(FaceState(expression=FaceExpression.CURIOUS, reaction_strength=1, eye_open=1.12,
                            eye_asymmetry=.18))
    right = render(FaceState(expression=FaceExpression.CURIOUS, reaction_strength=1, eye_open=1.12,
                             eye_asymmetry=-.18))
    symmetric = render(FaceState(expression=FaceExpression.CURIOUS, reaction_strength=1, eye_open=1.23,
                                 eye_asymmetry=0))

    assert left.eyes[0].radius_y > left.eyes[1].radius_y
    assert right.eyes[1].radius_y > right.eyes[0].radius_y
    assert left.eyes[0].radius_y == right.eyes[1].radius_y
    assert left.eyes[1].radius_y == right.eyes[0].radius_y
    assert symmetric.eyes[0].radius_y == symmetric.eyes[1].radius_y


def test_explicit_eye_asymmetry_interpolates_each_eye_through_neutral():
    renderer = EyeRenderer(transition_seconds=.2)
    renderer.render(FaceState(eye_asymmetry=.18), timestamp=0)
    halfway = renderer.render(FaceState(eye_asymmetry=-.18), timestamp=.1)
    completed = renderer.render(FaceState(eye_asymmetry=-.18), timestamp=.2)

    assert abs(halfway.eyes[0].radius_y - halfway.eyes[1].radius_y) < abs(completed.eyes[0].radius_y - completed.eyes[1].radius_y)
    assert completed.eyes[1].radius_y > completed.eyes[0].radius_y


def test_tk_draws_separate_eye_body_iris_pupil_and_highlights():
    frame = EyeRenderer(iris_color="amber").render(FaceState(), timestamp=0)
    display = object.__new__(TkEyeDisplay)
    calls = []
    display._canvas = SimpleNamespace(
        create_oval=lambda *args, **kwargs: calls.append(kwargs),
        create_arc=lambda *args, **kwargs: calls.append(kwargs),
    )
    display._tk = SimpleNamespace(ARC="arc")

    display._draw_eye(frame.eyes[0], frame)

    fills = [call.get("fill") for call in calls]
    assert len(calls) == 8
    assert frame.iris_color in fills
    assert frame.pupil_color in fills
    assert "#071522" in fills
