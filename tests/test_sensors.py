"""Environmental service/adapter checks without I2C libraries or hardware."""
import asyncio
import json
import sys
from threading import Event
from types import SimpleNamespace

import pytest

from robot.config import ConfigurationError, RuntimeConfig, load_document
from robot.hardware.bme280 import BME280Provider
from robot.lifecycle import LifecycleService
from robot.runtime import build_runtime
from robot.sensors import EnvironmentalReading, EnvironmentalSensorService
from robot.ui import MemoryEyeDisplay


READING = EnvironmentalReading(22.5, 48.25, 1008.75)


class FakeProvider:
    def __init__(self):
        self.starts = self.reads = self.closes = 0

    def start(self):
        self.starts += 1

    def read(self):
        self.reads += 1
        return READING

    def close(self):
        self.closes += 1


def service(provider, **kwargs):
    return EnvironmentalSensorService(lambda: provider, enabled=True,
        poll_interval_seconds=5, stale_after_seconds=30, **kwargs)


class Steps:
    """Drive the synchronous worker's waits without real elapsed time."""
    def __init__(self, count, callback=lambda: None):
        self.count, self.callback = count, callback
        self.delays = []

    def is_set(self):
        return False

    def wait(self, delay):
        self.delays.append(delay)
        self.callback()
        return len(self.delays) >= self.count


@pytest.mark.parametrize("enabled", [False, True])
def test_runtime_owns_sensor_and_disabled_never_constructs_provider(enabled):
    provider = FakeProvider()
    calls = []
    def factory():
        calls.append(True)
        return provider

    async def exercise():
        display = MemoryEyeDisplay()
        runtime = build_runtime(config=RuntimeConfig(environmental_enabled=enabled),
                                eye_display=display, sensor_provider_factory=factory)
        await runtime.start()
        try:
            for _ in range(100):
                if not enabled or runtime.sensor_status()["environmental"]["available"]:
                    break
                await asyncio.sleep(.01)
            state = runtime.sensor_status()["environmental"]
            assert state["status"] == ("available" if enabled else "disabled")
            assert state["measurements"] == ({"temperature_c": 22.5,
                "humidity_percent": 48.25, "pressure_hpa": 1008.75} if enabled else None)
            assert runtime.core.is_running
            json.dumps(state, allow_nan=False)
        finally:
            await runtime.stop()
        assert provider.starts == provider.reads == provider.closes == int(enabled)
        assert len(calls) == int(enabled)
        assert display.frames
    asyncio.run(exercise())


def test_polling_updates_and_stale_values_are_not_current():
    now = [10.0]
    provider = FakeProvider()
    sensor = service(provider, clock=lambda: now[0])
    snapshots = []
    def tick():
        snapshots.append(sensor.snapshot())
        now[0] += 5
    sensor._stop = Steps(3, tick)
    sensor._run()
    assert provider.reads == 3 and provider.starts == provider.closes == 1
    assert sensor._stop.delays == [5, 5, 5]
    assert all(s["available"] and s["age_seconds"] == 0 for s in snapshots)
    assert snapshots[-1]["last_update"].endswith("+00:00")
    now[0] += 30
    stale = sensor.snapshot()
    assert stale["status"] == "stale" and stale["measurements"] is None
    assert stale["last_update"] == snapshots[-1]["last_update"]


def test_transient_failure_invalidates_previous_reading_then_recovers():
    class Provider(FakeProvider):
        def read(self):
            self.reads += 1
            if self.reads == 2:
                raise OSError("transient bus fault")
            return READING
    provider = Provider()
    sensor = service(provider)
    snapshots = []
    sensor._stop = Steps(3, lambda: snapshots.append(sensor.snapshot()))
    sensor._run()
    assert [s["status"] for s in snapshots] == ["available", "unavailable", "available"]
    assert snapshots[1]["measurements"] is None
    assert snapshots[1]["last_update"] is not None
    assert snapshots[1]["error"] == "OSError"
    assert snapshots[2]["error"] is None
    assert provider.starts == provider.closes == 2


def test_absent_sensor_retries_with_bounded_backoff_and_rate_limited_logs(caplog):
    class Provider(FakeProvider):
        def start(self):
            self.starts += 1
            raise OSError("absent")
    now = [0]
    provider = Provider()
    sensor = service(provider, clock=lambda: now[0])
    sensor._stop = Steps(7)
    sensor._run()
    assert sensor._stop.delays == [5, 10, 20, 40, 60, 60, 60]
    assert sensor.snapshot()["status"] == "unavailable"
    assert sensor.snapshot()["last_update"] is None
    assert provider.starts == provider.closes == 7 and not provider.reads
    assert caplog.text.count("Environmental sensor unavailable") == 1


def test_missing_dependency_or_bad_provider_is_isolated():
    def missing():
        raise ImportError("optional driver missing")
    sensor = EnvironmentalSensorService(missing, enabled=True, poll_interval_seconds=5, stale_after_seconds=30)
    sensor._stop = Steps(1)
    sensor._run()
    assert sensor.snapshot()["error"] == "ImportError"
    provider = FakeProvider()
    provider.read = lambda: {"temperature": 0}
    sensor = service(provider)
    sensor._stop = Steps(1)
    sensor._run()
    assert sensor.snapshot()["error"] == "ValueError"


def test_slow_io_keeps_rendering_and_shutdown_bounded_without_late_publish():
    entered, release, closed = Event(), Event(), Event()
    class Provider(FakeProvider):
        def read(self):
            entered.set()
            release.wait(5)
            return READING
        def close(self):
            closed.set()
    async def exercise():
        display = MemoryEyeDisplay()
        runtime = build_runtime(config=RuntimeConfig(environmental_enabled=True),
            eye_display=display, sensor_provider_factory=Provider)
        await runtime.start()
        try:
            for _ in range(100):
                if entered.is_set():
                    break
                await asyncio.sleep(.01)
            assert entered.is_set()
            await asyncio.sleep(.1)
            assert len(display.frames) >= 2
            await asyncio.wait_for(runtime.stop(), 2)
            assert runtime.sensor_status()["environmental"]["status"] == "stopped"
            assert not closed.is_set()  # Never close a bus during its read.
        finally:
            release.set()
            await runtime.stop()
        assert closed.is_set()
        assert runtime.sensor_status()["environmental"]["measurements"] is None
    asyncio.run(exercise())


def test_initialization_timeout_is_unavailable():
    sensor = service(FakeProvider(), clock=lambda: 100)
    sensor._started_at = 0
    assert sensor.snapshot()["status"] == "unavailable"
    assert sensor.snapshot()["measurements"] is None


@pytest.mark.parametrize("values", [(float("nan"), 50, 1000), (20, float("inf"), 1000),
    (True, 50, 1000), (20, -1, 1000), (20, 101, 1000), (20, 50, 0)])
def test_invalid_readings_rejected(values):
    with pytest.raises(ValueError):
        EnvironmentalReading(*values)


@pytest.mark.parametrize("address", [0x76, 0x77])
def test_environmental_maps_units_calibration_and_configured_address(monkeypatch, address):
    calls = []
    class Bus:
        def __init__(self, bus):
            calls.append(("bus", bus))
        def read_byte_data(self, addr, reg):
            calls.append(("id", addr, reg))
            return 0x60
        def close(self):
            calls.append(("close",))
    def calibrate(bus, addr):
        calls.append(("calibrate", addr))
        return "calibration"
    def sample(bus, addr, calibration):
        calls.append(("sample", addr, calibration))
        return SimpleNamespace(temperature=22.5, humidity=48.25, pressure=1008.75)
    monkeypatch.setitem(sys.modules, "smbus2", SimpleNamespace(SMBus=Bus))
    monkeypatch.setitem(sys.modules, "bme280", SimpleNamespace(load_calibration_params=calibrate, sample=sample))
    provider = BME280Provider(address=address)
    provider.start()
    assert provider.read() == READING
    provider.close()
    provider.close()
    assert calls == [("bus", 1), ("id", address, 0xD0), ("calibrate", address),
                     ("sample", address, "calibration"), ("close",)]


def test_wrong_chip_releases_partially_initialized_bus(monkeypatch):
    closed = []
    monkeypatch.setitem(sys.modules, "smbus2", SimpleNamespace(SMBus=lambda _: SimpleNamespace(
        read_byte_data=lambda *a: 0x58, close=lambda: closed.append(True))))
    monkeypatch.setitem(sys.modules, "bme280", SimpleNamespace())
    provider = BME280Provider(address=0x76)
    with pytest.raises(ValueError, match="not a BME280"):
        provider.start()
    assert closed == [True]


@pytest.mark.parametrize("field,value", [("type", "unknown"), ("type", []), ("type", None), ("enabled", 1), ("i2c_address", "0x75"),
    ("i2c_address", 118), ("i2c_address", []), ("poll_interval_seconds", 0),
    ("poll_interval_seconds", .5), ("poll_interval_seconds", True),
    ("poll_interval_seconds", float("nan")), ("stale_after_seconds", 5),
    ("stale_after_seconds", float("inf"))])
def test_sensor_config_validation(tmp_path, field, value):
    document = load_document()
    document["sensors"]["environmental"][field] = value
    with pytest.raises(ConfigurationError):
        RuntimeConfig.from_dict(document, base_dir=tmp_path)


def test_sensor_settings_require_restart_and_snapshot_is_live(tmp_path):
    path = tmp_path / "phos.json"
    config = RuntimeConfig(log_file=None)
    config.save(path)
    config = RuntimeConfig.from_file(path)
    lifecycle = LifecycleService(path, config)
    sensor = service(FakeProvider())
    lifecycle.register_sensor_status(lambda: {"environmental": sensor.snapshot()})
    document = load_document(path)
    document["sensors"]["environmental"].update(type="bmp280", enabled=True, i2c_address="0x77",
        poll_interval_seconds=10, stale_after_seconds=60)
    path.write_text(json.dumps(document))
    result = lifecycle.execute("reload")
    assert result["ok"] and not result["applied"] and not result["reloadable"]
    assert len(result["restart_required"]) == 5
    assert all(p.startswith("sensors.environmental.") for p in result["restart_required"])
    assert not result["active"]["sensors"]["environmental"]["enabled"]
    sensor._stop = Steps(1)
    sensor._run()
    state = lifecycle.execute("status")["sensors"]["environmental"]
    assert state["available"]
    assert json.loads(json.dumps(state))["measurements"]["temperature_c"] == 22.5


def test_runtime_passes_configured_address_and_sensor_failure_does_not_stop_core(monkeypatch):
    addresses = []
    class Missing(FakeProvider):
        def start(self):
            raise OSError("device absent")
    def factory(*, address):
        addresses.append(address)
        return Missing()
    factory.available_measurements = BME280Provider.available_measurements
    monkeypatch.setattr("robot.hardware.environmental.BME280Provider", factory)
    async def exercise():
        display = MemoryEyeDisplay()
        runtime = build_runtime(config=RuntimeConfig(environmental_enabled=True, environmental_i2c_address="0x77"),
                                eye_display=display)
        stop = asyncio.Event()
        runner = asyncio.create_task(runtime.run(stop))
        try:
            for _ in range(100):
                if runtime.sensor_status()["environmental"]["status"] == "unavailable":
                    break
                await asyncio.sleep(.01)
            assert runtime.sensor_status()["environmental"]["status"] == "unavailable"
            assert runtime.core.is_running and not runner.done() and display.frames
        finally:
            stop.set()
            await runner
    asyncio.run(exercise())
    assert addresses == [0x77]


def test_stop_during_initialization_closes_without_reading_and_allows_clean_restart():
    entered, release = Event(), Event()
    class SlowStart(FakeProvider):
        def start(self):
            self.starts += 1
            entered.set()
            release.wait(5)
    provider = SlowStart()
    sensor = service(provider)
    async def exercise():
        await sensor.start()
        try:
            for _ in range(100):
                if entered.is_set():
                    break
                await asyncio.sleep(.01)
            assert entered.is_set()
            await sensor.stop()
            assert sensor.snapshot()["status"] == "stopped"
            with pytest.raises(RuntimeError, match="still stopping"):
                await sensor.start()
        finally:
            release.set()
            await sensor.stop()
        assert provider.closes == 1 and provider.reads == 0
        await sensor.start()
        for _ in range(100):
            if sensor.snapshot()["available"]:
                break
            await asyncio.sleep(.01)
        assert sensor.snapshot()["available"]
        await sensor.stop()
        assert provider.closes == 2 and provider.reads == 1
    asyncio.run(exercise())


def test_sensor_snapshot_crosses_existing_lifecycle_process_channel(tmp_path):
    import multiprocessing
    from threading import Thread
    from robot.lifecycle_channel import LifecycleClient, serve_lifecycle
    config = RuntimeConfig(log_file=None)
    path = tmp_path / "phos.json"
    config.save(path)
    lifecycle = LifecycleService(path, RuntimeConfig.from_file(path))
    sensor = service(FakeProvider())
    lifecycle.register_sensor_status(lambda: {"environmental": sensor.snapshot()})
    parent, child = multiprocessing.Pipe()
    stop = Event()
    worker = Thread(target=serve_lifecycle, args=(parent, lifecycle, stop))
    worker.start()
    try:
        client = LifecycleClient(child)
        assert client.execute("status")["sensors"]["environmental"]["status"] == "starting"
        sensor._stop = Steps(1)
        sensor._run()
        assert client.execute("status")["sensors"]["environmental"]["measurements"]["pressure_hpa"] == 1008.75
    finally:
        stop.set()
        child.close()
        worker.join(timeout=2)
    assert not worker.is_alive()


@pytest.mark.parametrize("temperature,pressure", [(-41, 1000), (86, 1000), (20, 299), (20, 1101)])
def test_environmental_rejects_out_of_range_compensated_samples(temperature, pressure):
    provider = BME280Provider(address=0x76)
    provider._bus = object()
    provider._driver = SimpleNamespace(sample=lambda *args: SimpleNamespace(
        temperature=temperature, humidity=50, pressure=pressure))
    with pytest.raises(ValueError, match="measurement range"):
        provider.read()


def test_existing_configuration_requires_explicit_sensor_section_migration(tmp_path):
    document = load_document()
    del document["sensors"]
    with pytest.raises(ConfigurationError, match="missing fields: sensors"):
        RuntimeConfig.from_dict(document, base_dir=tmp_path)


@pytest.mark.parametrize('sensor_type', ['bme280', 'bmp280'])
def test_provider_selection(sensor_type):
    from robot.hardware.environmental import environmental_provider_type
    from robot.hardware.bmp280 import BMP280Provider
    assert environmental_provider_type(sensor_type) is (BME280Provider if sensor_type == 'bme280' else BMP280Provider)


@pytest.mark.parametrize('humidity,status', [(None, 'available'), (45, 'unavailable')])
def test_bmp280_capabilities_validate_readings(humidity, status):
    class Provider(FakeProvider):
        def read(self):
            return EnvironmentalReading(22.5, humidity, 1008.75)
    sensor = service(Provider(), sensor_type='bmp280',
                     available_measurements=('temperature_c', 'pressure_hpa'))
    sensor._stop = Steps(1)
    sensor._run()
    state = sensor.snapshot()
    assert state['sensor_type'] == 'bmp280'
    assert state['available_measurements'] == ['temperature_c', 'pressure_hpa']
    assert state['status'] == status
    if humidity is None:
        assert state['measurements']['humidity_percent'] is None
        json.dumps(state, allow_nan=False)


def test_bme280_requires_humidity():
    provider = FakeProvider()
    provider.read = lambda: EnvironmentalReading(22.5, None, 1008.75)
    sensor = service(provider)
    sensor._stop = Steps(1)
    sensor._run()
    assert sensor.snapshot()['status'] == 'unavailable'


@pytest.mark.parametrize('address', [0x76, 0x77])
def test_bmp280_adapter_and_bus_ownership(monkeypatch, address):
    from robot.hardware.bmp280 import BMP280Provider
    calls = []
    bus = SimpleNamespace(read_byte_data=lambda addr, reg: 0x58,
                          close=lambda: calls.append('close'))
    def driver(*, i2c_addr, i2c_dev):
        assert i2c_addr == address and i2c_dev is bus
        return SimpleNamespace(setup=lambda **kw: calls.append(kw),
            update_sensor=lambda: calls.append('sample'), temperature=22.5, pressure=1008.75)
    monkeypatch.setitem(sys.modules, 'smbus2', SimpleNamespace(SMBus=lambda n: bus if n == 1 else None))
    monkeypatch.setitem(sys.modules, 'bmp280', SimpleNamespace(BMP280=driver))
    provider = BMP280Provider(address=address)
    provider.start()
    assert provider.read() == EnvironmentalReading(22.5, None, 1008.75)
    provider.close()
    provider.close()
    assert calls == [{'mode': 'forced'}, 'sample', 'close']


@pytest.mark.parametrize('chip', [0x60, 0])
def test_bmp280_wrong_chip_closes_bus(monkeypatch, chip):
    from robot.hardware.bmp280 import BMP280Provider
    closed = []
    monkeypatch.setitem(sys.modules, 'smbus2', SimpleNamespace(SMBus=lambda n: SimpleNamespace(
        read_byte_data=lambda *a: chip, close=lambda: closed.append(True))))
    monkeypatch.setitem(sys.modules, 'bmp280', SimpleNamespace(BMP280=None))
    with pytest.raises(ValueError, match='not a BMP280'):
        BMP280Provider(address=0x76).start()
    assert closed == [True]


@pytest.mark.parametrize('sensor_type', ['bme280', 'bmp280'])
def test_runtime_selects_provider_and_capabilities(monkeypatch, sensor_type):
    from robot.hardware.environmental import environmental_provider_type
    selected = environmental_provider_type(sensor_type)
    calls = []
    monkeypatch.setattr(selected, 'start', lambda self: calls.append(self._address))
    monkeypatch.setattr(selected, 'close', lambda self: None)
    monkeypatch.setattr(selected, 'read', lambda self: EnvironmentalReading(
        22.5, 48.25 if sensor_type == 'bme280' else None, 1008.75))
    async def exercise():
        runtime = build_runtime(config=RuntimeConfig(environmental_enabled=True,
            environmental_type=sensor_type, environmental_i2c_address='0x77'), eye_display=MemoryEyeDisplay())
        await runtime.start()
        try:
            for _ in range(100):
                state = runtime.sensor_status()['environmental']
                if state['available']:
                    break
                await asyncio.sleep(.01)
            assert state['available'] and state['sensor_type'] == sensor_type
            assert ('humidity_percent' in state['available_measurements']) == (sensor_type == 'bme280')
        finally:
            await runtime.stop()
    asyncio.run(exercise())
    assert calls == [0x77]
