from pathlib import Path

from robot.vision.detector import _default_cascade_path


class OpenCVWithoutData:
    pass


class OpenCVWithData:
    class data:
        haarcascades = "/custom/haarcascades"


def test_default_cascade_path_uses_raspberry_pi_os_location_when_cv2_data_is_unavailable():
    assert _default_cascade_path(OpenCVWithoutData()) == Path(
        "/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml"
    )


def test_default_cascade_path_uses_cv2_bundled_location_when_available():
    assert _default_cascade_path(OpenCVWithData()) == Path(
        "/custom/haarcascades/haarcascade_frontalface_default.xml"
    )
