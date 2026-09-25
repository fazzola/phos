"""MPU-6050 adapter, worker, runtime and configuration checks without hardware."""
import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from robot.config import ConfigurationError, RuntimeConfig, load_document
from robot.hardware.mpu6050 import MPU6050Provider
from robot.lifecycle import LifecycleService
from robot.runtime import build_runtime
from robot.sensors import IMUReading, IMUSensorService
from robot.ui import MemoryEyeDisplay


class Bus:
    def __init__(self, identity=0x68, data=None):
        self.identity, self.data, self.calls = identity, data or [0, 0, 0x40, 0, 0xC0, 0, 0, 0, 0, 0x83, 0, 0xFF, 0xFF, 0x7D], []
    def read_byte_data(self, address, register): self.calls.append(("read", address, register)); return self.identity
    def write_byte_data(self, *args): self.calls.append(("write", *args))
    def read_i2c_block_data(self, *args): self.calls.append(("sample", *args)); return self.data
    def close(self): self.calls.append(("close",))


@pytest.fixture
def adapter(monkeypatch):
    bus, opened = Bus(), []
    monkeypatch.setitem(sys.modules, "smbus2", SimpleNamespace(SMBus=lambda number: opened.append(number) or bus))
    return bus, opened


@pytest.mark.parametrize("address", [0x68, 0x69])
def test_adapter_initializes_maps_units_and_closes(adapter, address):
    bus, opened = adapter
    provider = MPU6050Provider(address=address)
    assert not opened
    provider.start()
    assert opened == [1]
    assert ("read", address, 0x75) in bus.calls
    assert ("write", address, 0x6B, 0) in bus.calls
    assert ("write", address, 0x1C, 0) in bus.calls
    assert ("write", address, 0x1B, 0) in bus.calls
    reading = provider.read()
    assert reading.acceleration_y_m_s2 == pytest.approx(9.80665)
    assert reading.acceleration_z_m_s2 == pytest.approx(-9.80665)
    assert reading.angular_velocity_y_deg_s == pytest.approx(255 / 131)
    assert reading.angular_velocity_z_deg_s == pytest.approx(-1)
    provider.close(); provider.close()
    assert bus.calls[-1] == ("close",) and bus.calls.count(("close",)) == 1


@pytest.mark.parametrize("identity,data", [(0, None), (0x68, [0] * 13)])
def test_adapter_rejects_wrong_device_or_incomplete_sample(adapter, identity, data):
    bus, _ = adapter; bus.identity = identity
    provider = MPU6050Provider(address=0x68)
    if identity != 0x68:
        with pytest.raises(ValueError, match="WHO_AM_I"): provider.start()
        assert bus.calls[-1] == ("close",)
    else:
        provider.start(); bus.data = data
        with pytest.raises(OSError, match="incomplete"): provider.read()


class FakeIMU:
    def __init__(self, fail=False): self.starts = self.reads = self.closes = 0; self.fail = fail
    def start(self): self.starts += 1
    def close(self): self.closes += 1
    def read(self):
        self.reads += 1
        if self.fail and self.reads == 1: raise OSError("bus fault")
        return IMUReading(1, 2, 3, 4, 5, 6)


class Steps:
    def __init__(self, count): self.count, self.delays = count, []
    def is_set(self): return False
    def wait(self, delay): self.delays.append(delay); return len(self.delays) >= self.count


def test_imu_service_transient_failure_recovers_and_serializes():
    provider = FakeIMU(fail=True)
    sensor = IMUSensorService(lambda: provider, enabled=True, poll_interval_seconds=5, stale_after_seconds=30)
    sensor._stop = Steps(2); sensor._run()
    state = sensor.snapshot()
    assert state["available"] and state["measurements"] == {"acceleration_x_m_s2": 1, "acceleration_y_m_s2": 2, "acceleration_z_m_s2": 3, "angular_velocity_x_deg_s": 4, "angular_velocity_y_deg_s": 5, "angular_velocity_z_deg_s": 6}
    assert state["calibration"] == "factory_scale_only" and provider.starts == provider.closes == 2
    json.dumps(state, allow_nan=False)


@pytest.mark.parametrize("enabled", [False, True])
def test_runtime_imu_disabled_never_opens_provider(enabled):
    provider, calls = FakeIMU(), []
    def factory(): calls.append(True); return provider
    async def exercise():
        runtime = build_runtime(config=RuntimeConfig(imu_enabled=enabled), eye_display=MemoryEyeDisplay(), imu_provider_factory=factory)
        await runtime.start()
        try:
            for _ in range(100):
                state = runtime.sensor_status()["imu"]
                if state["status"] != "starting": break
                await asyncio.sleep(.01)
            assert state["status"] == ("available" if enabled else "disabled")
        finally: await runtime.stop()
    asyncio.run(exercise()); assert len(calls) == int(enabled)


@pytest.mark.parametrize("field,value", [("enabled", 1), ("i2c_address", "0x67"), ("poll_interval_seconds", 0), ("stale_after_seconds", 5)])
def test_imu_configuration_validation(field, value, tmp_path):
    document = load_document(); document["sensors"]["imu"][field] = value
    with pytest.raises(ConfigurationError): RuntimeConfig.from_dict(document, base_dir=tmp_path)


def test_imu_restart_policy(tmp_path):
    path = tmp_path / "phos.json"; RuntimeConfig(log_file=None).save(path)
    lifecycle = LifecycleService(path, RuntimeConfig.from_file(path))
    document = load_document(path)
    document["sensors"]["imu"].update(enabled=True, i2c_address="0x69", poll_interval_seconds=10, stale_after_seconds=60)
    path.write_text(json.dumps(document)); result = lifecycle.execute("reload")
    assert result["ok"] and result["applied"] == []
    assert result["restart_required"] == sorted("sensors.imu." + name for name in document["sensors"]["imu"])
