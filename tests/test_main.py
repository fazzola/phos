import asyncio

from robot.runtime import build_runtime
from robot.ui import MemoryEyeDisplay


def test_runtime_starts_and_stops_registered_components():
    async def exercise():
        display = MemoryEyeDisplay()
        runtime = build_runtime(eye_display=display)
        stop_event = asyncio.Event()
        stop_event.set()
        await runtime.run(stop_event)
        return runtime.core, display

    core, display = asyncio.run(exercise())

    assert not core.is_running
    assert display.frames


def test_web_worker_failure_stops_runtime_and_propagates_for_service_recovery(monkeypatch):
    import pytest
    from robot import main
    stopped = []
    class Runtime:
        async def run(self, stop):
            await stop.wait()
            stopped.append(True)
    class Worker:
        def check_running(self):
            raise RuntimeError('Web administration worker stopped unexpectedly')
    monkeypatch.setattr(main, 'build_application', lambda **kw: Runtime())
    monkeypatch.setattr(main, '_install_shutdown_handlers', lambda *args: None)
    with pytest.raises(RuntimeError, match='worker stopped unexpectedly'):
        asyncio.run(main.async_main(web_server=Worker()))
    assert stopped == [True]
