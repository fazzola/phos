"""Picamera2 resource ownership tested without the vendor package or hardware."""
import asyncio
import sys
from types import SimpleNamespace

import pytest

from robot.vision.camera import Picamera2CameraProvider


@pytest.mark.parametrize("failure", ["configure", "start", "stop"])
def test_camera_closes_after_driver_failure(monkeypatch, failure):
    calls = []
    def record(name):
        calls.append(name)
        if name == failure:
            raise RuntimeError(name)
    driver = SimpleNamespace(create_preview_configuration=lambda **kw: {},
                             configure=lambda config: record("configure"),
                             start=lambda: record("start"), stop=lambda: record("stop"),
                             close=lambda: record("close"))
    monkeypatch.setitem(sys.modules, "picamera2", SimpleNamespace(Picamera2=lambda: driver))
    async def exercise():
        camera = Picamera2CameraProvider()
        with pytest.raises(RuntimeError, match=failure):
            await camera.start()
            await camera.stop()
        await camera.stop()  # Repeated shutdown must not reuse the closed driver.
        assert camera._camera is None
    asyncio.run(exercise())
    assert calls[-1] == "close" and calls.count("close") == 1
