"""Lifecycle policy and process channel tests without hardware or OS commands."""
import asyncio
from copy import deepcopy
import json
import logging
import multiprocessing
from threading import Event, Thread

import pytest

from robot.config import RuntimeConfig, load_document
from robot.lifecycle import LifecycleService, apply_log_level
from robot.lifecycle_channel import LifecycleClient, serve_lifecycle


@pytest.fixture
def runtime(tmp_path):
    document = load_document()
    document["logging"]["file"] = None
    path = tmp_path / "phos.json"
    path.write_text(json.dumps(document))
    applied = []
    now = [0.0]
    service = LifecycleService(path, RuntimeConfig.from_file(path), restart_supported=True,
                               log_level_setter=applied.append, clock=lambda: now[0])
    return path, service, applied, now


def update(path, edit):
    document = load_document(path)
    edit(document)
    path.write_text(json.dumps(document))


def test_reload_applies_only_safe_changes_and_reports_pending(runtime):
    path, service, applied, _ = runtime
    update(path, lambda d: (d["logging"].update(level="DEBUG"), d["display"].update(fps=20)))
    before = path.read_bytes()
    result = service.execute("reload")
    assert result["ok"] and result["applied"] == ["logging.level"]
    assert applied == ["DEBUG"]
    assert result["active"]["logging"]["level"] == "DEBUG"
    assert result["active"]["display"]["fps"] == 30
    assert result["restart_required"] == ["display.fps"]
    assert result["loaded_at"] and result["config_path"] == str(path)
    assert path.read_bytes() == before
    assert service.execute("reload")["applied"] == []


@pytest.mark.parametrize("bad", ["number", "path", "json", "secret"])
def test_invalid_configuration_never_partially_applies_or_restarts(runtime, bad):
    path, service, applied, _ = runtime
    previous = deepcopy(service.active)
    loaded_at = service.loaded_at
    def invalid(d):
        d["logging"]["level"] = "DEBUG"
        if bad == "number":
            d["display"]["fps"] = 0
        elif bad == "path":
            d["expression"]["enabled"] = True
            d["expression"]["local"]["model_path"] = "absent.onnx"
        else:
            d["AWS_SECRET_ACCESS_KEY"] = "secret-value"
    update(path, invalid)
    if bad == "json":
        path.write_text('{')
    for operation in ("reload", "restart"):
        result = service.execute(operation)
        assert not result["ok"] and "secret-value" not in str(result)
    assert service.active == previous and service.loaded_at == loaded_at
    assert not applied and service.restart_at is None


def test_restart_and_allowlist(runtime):
    _, service, _, now = runtime
    for operation in ("reboot", "sh -c anything", {"command": "anything"}, None):
        assert not service.execute(operation)["ok"]
    assert service.restart_at is None
    assert service.execute("restart")["restart_requested"]
    assert not service.restart_due
    deadline = service.restart_at
    now[0] += .5
    assert service.execute("restart")["ok"]
    assert service.restart_at == deadline
    assert not service.execute("reload")["ok"]
    now[0] += 1
    assert service.restart_due


def test_manual_start_cannot_request_supervised_restart(runtime):
    _, service, _, _ = runtime
    service.restart_supported = False
    assert not service.execute("restart")["ok"]
    assert service.restart_at is None
    assert service.execute("reload")["ok"]


def test_log_reload_retains_sdk_suppression():
    root, boto, botocore = logging.getLogger(), logging.getLogger("boto3"), logging.getLogger("botocore")
    original = root.level, boto.level, botocore.level
    try:
        apply_log_level("DEBUG")
        assert root.level == logging.DEBUG
        assert boto.level == botocore.level == logging.WARNING
    finally:
        root.setLevel(original[0])
        boto.setLevel(original[1])
        botocore.setLevel(original[2])


def test_local_channel_updates_parent_service(runtime):
    path, service, applied, _ = runtime
    parent, child = multiprocessing.Pipe()
    stop = Event()
    thread = Thread(target=serve_lifecycle, args=(parent, service, stop))
    thread.start()
    try:
        client = LifecycleClient(child)
        assert client.execute("status")["ok"]
        update(path, lambda d: d["logging"].update(level="ERROR"))
        assert client.execute("reload")["applied"] == ["logging.level"]
        assert applied == ["ERROR"]
        assert not client.execute("reboot")["ok"]
        assert client.execute("restart")["restart_requested"]
        assert service.restart_at is not None
    finally:
        stop.set()
        child.close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_restart_request_stops_runtime_through_existing_stop_event(runtime, monkeypatch):
    from robot import main
    _, service, _, now = runtime
    service.execute("restart")
    now[0] = 2.0
    stopped = []
    class Runtime:
        async def run(self, stop):
            await asyncio.wait_for(stop.wait(), timeout=1)
            stopped.append(True)
    monkeypatch.setattr(main, "build_application", lambda **kw: Runtime())
    monkeypatch.setattr(main, "_install_shutdown_handlers", lambda *args: None)
    asyncio.run(main.async_main(lifecycle=service))
    assert stopped == [True]


def test_main_exits_with_restart_code_after_worker_cleanup(runtime, monkeypatch):
    from robot import main
    path, service, _, _ = runtime
    calls = []
    class Worker:
        lifecycle = service
        def __init__(self, *args):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            calls.append("cleanup")
    async def run(**kwargs):
        assert kwargs["lifecycle"].execute("restart")["ok"]
    monkeypatch.setattr("robot.web.server.WebServer", Worker)
    monkeypatch.setattr(main, "async_main", run)
    monkeypatch.setattr(main.logging, "basicConfig", lambda **kw: None)
    monkeypatch.setattr("sys.argv", ["phos", "--config", str(path)])
    with pytest.raises(SystemExit) as error:
        main.main()
    assert error.value.code == 75 and calls == ["cleanup"]


def test_deployment_contract_and_restart_capability(runtime, monkeypatch):
    from configparser import ConfigParser
    from pathlib import Path
    from robot.lifecycle import RESTART_EXIT_CODE
    from robot.web.server import WebServer
    path, _, _, _ = runtime
    unit = ConfigParser(interpolation=None)
    unit.read(Path(__file__).resolve().parents[1] / "deploy/phos.service")
    assert unit["Unit"]["After"] == "graphical-session-pre.target"
    assert unit["Unit"]["PartOf"] == "graphical-session.target"
    assert unit["Service"]["RestartForceExitStatus"] == str(RESTART_EXIT_CODE)
    assert unit["Service"]["ExecStart"].endswith("--config %h/phos/config/phos.json")
    config = RuntimeConfig.from_file(path)
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    monkeypatch.setenv("PHOS_SERVICE_MANAGED", "1")
    assert not WebServer(path, config).lifecycle.restart_supported
    monkeypatch.setenv("INVOCATION_ID", "test-systemd-invocation")
    assert WebServer(path, config).lifecycle.restart_supported
    monkeypatch.delenv("PHOS_SERVICE_MANAGED")
    assert not WebServer(path, config).lifecycle.restart_supported
