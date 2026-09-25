"""CCS811 register, service and runtime checks without hardware or smbus2."""
import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from robot.config import ConfigurationError, RuntimeConfig, load_document
from robot.hardware.ccs811 import CCS811Provider
from robot.lifecycle import LifecycleService
from robot.runtime import build_runtime
from robot.sensors import (AirQualityReading, AirQualitySensorService, EnvironmentalCompensation,
                           EnvironmentalReading, EnvironmentalSensorService, SensorNotReady)
from robot.ui import MemoryEyeDisplay


class Steps:
    def __init__(self, count, callback=lambda: None):
        self.count, self.callback, self.delays = count, callback, []

    def is_set(self):
        return False

    def wait(self, delay):
        self.delays.append(delay)
        self.callback()
        return len(self.delays) >= self.count


class Bus:
    def __init__(self):
        self.calls = []
        self.chip = 0x81
        self.status = 0x10
        self.mode = 0
        self.app_start_works = True
        self.error = 0
        self.data = [0x04, 0xD2, 0x01, 0x41, 0x98, 0, 0, 0]  # 1234 ppm / 321 ppb

    def read_byte_data(self, address, register):
        self.calls.append(('read', address, register))
        return {0x20: self.chip, 0x00: self.status, 0xE0: self.error, 0x01: self.mode}[register]

    def write_byte(self, *args):
        self.calls.append(('command', *args))
        if args[1] == 0xF4 and self.app_start_works:
            self.status = 0x98

    def write_byte_data(self, *args):
        self.calls.append(('write', *args))
        if args[1] == 0x01:
            self.mode = args[2]

    def write_i2c_block_data(self, *args):
        self.calls.append(('block', *args))

    def read_i2c_block_data(self, *args):
        self.calls.append(('sample', *args))
        return self.data

    def close(self):
        self.calls.append(('close',))


@pytest.fixture
def adapter(monkeypatch):
    bus, now, delays, opened = Bus(), [100.0], [], []
    def open_bus(number):
        opened.append(number)
        return bus
    monkeypatch.setitem(sys.modules, 'smbus2', SimpleNamespace(SMBus=open_bus))
    def create(address=0x5a):
        return CCS811Provider(address=address, clock=lambda: now[0], sleep=delays.append)
    return create, bus, now, delays, opened


@pytest.mark.parametrize('address', [0x5a, 0x5b])
def test_initialization_mapping_conditioning_and_close(adapter, address):
    create, bus, now, delays, opened = adapter
    provider = create(address)
    assert not opened and not bus.calls
    provider.start()
    assert opened == [1] and delays == [.01]
    assert not any(c[0] == 'block' and c[2] == 0xFF for c in bus.calls)
    assert ('command', address, 0xF4) in bus.calls
    assert ('write', address, 0x01, 0x10) in bus.calls
    with pytest.raises(SensorNotReady) as error:
        provider.read()
    assert error.value.status == 'warming_up'
    now[0] += 1199
    with pytest.raises(SensorNotReady):
        provider.read()
    now[0] += 1
    assert provider.read() == AirQualityReading(1234, 321)
    provider.close()
    provider.close()
    assert bus.calls[-2:] == [('write', address, 0x01, 0), ('close',)]
    assert bus.calls.count(('close',)) == 1


@pytest.mark.parametrize('chip,status', [(0, 0x98), (0x81, 0x80), (0x81, 0x10), (0x81, 0x91)])
def test_bad_chip_firmware_mode_or_error_releases_bus(adapter, chip, status):
    create, bus, *_ = adapter
    bus.chip, bus.status, bus.error = chip, status, 0x20
    bus.app_start_works = False
    with pytest.raises((ValueError, OSError)):
        create().start()
    assert bus.calls[-1] == ('close',)
    if chip != 0x81:
        assert not any(c[0] == 'block' for c in bus.calls)


def test_compensation_encoding_deduplication_and_default_restore(adapter):
    create, bus, *_ = adapter
    provider = create()
    provider.start()
    provider.set_compensation(EnvironmentalCompensation(23.5, 48.5))
    provider.set_compensation(EnvironmentalCompensation(23.5, 48.5))
    provider.set_compensation(None)
    writes = [c for c in bus.calls if c[:3] == ('block', 0x5a, 0x05)]
    assert writes == [('block', 0x5a, 0x05, [0x61, 0, 0x61, 0]),
                      ('block', 0x5a, 0x05, [0x64, 0, 0x64, 0])]


@pytest.mark.parametrize('result', [[0]*7, [4, 210, 1, 65, 0x99, 0x20, 0, 0],
    [4, 210, 1, 65, 0, 0, 0, 0], [0, 0, 0, 0, 0x98, 0, 0, 0],
    [4, 210, 255, 255, 0x98, 0, 0, 0]])
def test_invalid_device_result_is_rejected(adapter, result):
    create, bus, now, *_ = adapter
    provider = create()
    provider.start()
    now[0] += 1200
    bus.data = result
    with pytest.raises((OSError, ValueError)):
        provider.read()


def test_data_not_ready_is_not_a_reinitialization_fault(adapter):
    create, bus, now, *_ = adapter
    provider = create()
    provider.start()
    now[0] += 1200
    bus.status = 0x90
    with pytest.raises(SensorNotReady) as error:
        provider.read()
    assert error.value.status == 'unavailable'
    assert not any(c[0] == 'sample' for c in bus.calls)


class FakeAir:
    def __init__(self):
        self.starts = self.reads = self.closes = 0
        self.compensations = []

    def start(self):
        self.starts += 1

    def set_compensation(self, values):
        self.compensations.append(values)

    def read(self):
        self.reads += 1
        return AirQualityReading(1234, 321)

    def close(self):
        self.closes += 1


def service(provider, **kwargs):
    return AirQualitySensorService(lambda: provider, enabled=True,
        poll_interval_seconds=5, stale_after_seconds=30, **kwargs)


def test_service_warmup_retains_provider_and_never_publishes_fake_values(adapter):
    create, bus, now, *_ = adapter
    sensor = service(create(), clock=lambda: now[0])
    states = []
    def tick():
        states.append(sensor.snapshot())
        now[0] += 600
    sensor._stop = Steps(3, tick)
    sensor._run()
    assert [s['status'] for s in states] == ['warming_up', 'warming_up', 'available']
    assert states[0]['measurements'] is states[0]['last_update'] is None
    assert states[2]['measurements'] == {'eco2_ppm': 1234, 'tvoc_ppb': 321}
    assert sensor._stop.delays == [5, 5, 5]
    assert len([c for c in bus.calls if c[0] == 'command']) == 1
    assert bus.calls.count(('close',)) == 1
    assert sensor.snapshot()['status'] == 'stale'
    assert sensor.snapshot()['measurements'] is None
    json.dumps(states, allow_nan=False)


def test_transient_failure_recovers_and_does_not_reuse_old_values(caplog):
    class Faulty(FakeAir):
        def read(self):
            self.reads += 1
            if self.reads == 2:
                raise OSError('bus fault')
            return AirQualityReading(1234, 321)
    provider = Faulty()
    sensor = service(provider)
    states = []
    sensor._stop = Steps(3, lambda: states.append(sensor.snapshot()))
    sensor._run()
    assert [s['status'] for s in states] == ['available', 'unavailable', 'available']
    assert states[1]['measurements'] is None and states[1]['error'] == 'OSError'
    assert provider.starts == provider.closes == 2
    assert 'bus fault' in caplog.text


def test_missing_device_backs_off_and_rate_limits(caplog):
    class Absent(FakeAir):
        def start(self):
            self.starts += 1
            raise OSError('absent')
    provider = Absent()
    sensor = service(provider, clock=lambda: 0)
    sensor._stop = Steps(7)
    sensor._run()
    assert sensor._stop.delays == [5, 10, 20, 40, 60, 60, 60]
    assert sensor.snapshot()['measurements'] is None
    assert caplog.text.count('Air-quality sensor unavailable') == 1


@pytest.mark.parametrize('humidity,source', [(48.5, 'environmental'), (None, 'device_defaults')])
def test_compensation_consumes_only_fresh_available_service_values(humidity, source):
    now = [100]
    env = EnvironmentalSensorService(lambda: SimpleNamespace(
        start=lambda: None, close=lambda: None, read=lambda: EnvironmentalReading(23.5, humidity, 1000)),
        enabled=True, poll_interval_seconds=5, stale_after_seconds=30, clock=lambda: now[0],
        available_measurements=('temperature_c', 'pressure_hpa') + (() if humidity is None else ('humidity_percent',)))
    env._stop = Steps(1)
    env._run()
    provider = FakeAir()
    air = service(provider, compensation_supplier=env.compensation)
    air._stop = Steps(1)
    air._run()
    assert air.snapshot()['compensation_input'] == source
    assert provider.compensations[-1] == (None if humidity is None else EnvironmentalCompensation(23.5, humidity))
    now[0] += 31
    air._run()
    assert provider.compensations[-1] is None
    assert air.snapshot()['compensation_input'] == 'device_defaults'


@pytest.mark.parametrize('values', [(True, 0), (-1, 3), (1234, float('nan')), (1234, -1)])
def test_air_quality_values_validate(values):
    with pytest.raises(ValueError):
        AirQualityReading(*values)


@pytest.mark.parametrize('field,value', [('enabled', 1), ('i2c_address', '0x76'), ('i2c_address', []),
    ('poll_interval_seconds', 0), ('poll_interval_seconds', True), ('poll_interval_seconds', float('inf')),
    ('stale_after_seconds', 5), ('stale_after_seconds', float('nan'))])
def test_configuration_validation(field, value, tmp_path):
    doc = load_document()
    doc['sensors']['ccs811'][field] = value
    with pytest.raises(ConfigurationError):
        RuntimeConfig.from_dict(doc, base_dir=tmp_path)


def test_configuration_migration_and_restart_policy(tmp_path):
    config = RuntimeConfig(log_file=None)
    path = tmp_path / 'phos.json'
    config.save(path)
    lifecycle = LifecycleService(path, RuntimeConfig.from_file(path))
    document = load_document(path)
    document['sensors']['ccs811'].update(enabled=True, i2c_address='0x5b',
                                       poll_interval_seconds=10, stale_after_seconds=60)
    path.write_text(json.dumps(document))
    result = lifecycle.execute('reload')
    assert result['ok'] and result['applied'] == []
    assert result['restart_required'] == sorted('sensors.ccs811.' + f for f in document['sensors']['ccs811'])
    assert result['active']['sensors']['ccs811']['enabled'] is False
    del document['sensors']['ccs811']
    with pytest.raises(ConfigurationError, match='ccs811'):
        RuntimeConfig.from_dict(document, base_dir=tmp_path)


@pytest.mark.parametrize('enabled,failure', [(False, False), (True, False), (True, True)])
def test_runtime_lifecycle_isolation_and_no_access_when_disabled(enabled, failure):
    provider, calls = FakeAir(), []
    def factory():
        calls.append(True)
        if failure:
            raise ImportError('missing dependency')
        return provider
    async def exercise():
        display = MemoryEyeDisplay()
        runtime = build_runtime(config=RuntimeConfig(ccs811_enabled=enabled), eye_display=display,
                                air_quality_provider_factory=factory)
        await runtime.start()
        try:
            for _ in range(100):
                state = runtime.sensor_status()['ccs811']
                if state['status'] != 'starting':
                    break
                await asyncio.sleep(.01)
            assert state['status'] == ('disabled' if not enabled else 'unavailable' if failure else 'available')
            assert state['sensor_type'] == 'ccs811'
            assert runtime.sensor_status()['environmental']['status'] == 'disabled'
            assert runtime.core.is_running and display.frames
        finally:
            await runtime.stop()
    asyncio.run(exercise())
    assert len(calls) == int(enabled)
    assert provider.closes == int(enabled and not failure)


def test_not_ready_polls_do_not_reconnect_or_flood_logs(caplog):
    import logging
    class Waiting(FakeAir):
        def read(self):
            self.reads += 1
            if self.reads % 2:
                raise SensorNotReady('Waiting for data')
            return AirQualityReading(1234, 321)
    provider = Waiting()
    sensor = service(provider, clock=lambda: 100)
    sensor._stop = Steps(8)
    with caplog.at_level(logging.INFO):
        sensor._run()
    assert provider.starts == provider.closes == 1
    assert sensor._stop.delays == [5]*8
    assert len(caplog.records) == 2  # One readiness message, one first reading.


def test_warmup_watchdog_detects_stalled_polling():
    now = [0]
    provider = FakeAir()
    def warming():
        raise SensorNotReady('Conditioning', warming_up=True)
    provider.read = warming
    sensor = service(provider, clock=lambda: now[0])
    sensor._stop = Steps(1)
    sensor._run()
    assert sensor.snapshot()['status'] == 'warming_up'
    now[0] = 31
    assert sensor.snapshot()['status'] == 'unavailable'


@pytest.mark.parametrize('kind,humidity', [('bme280', 45), ('bmp280', None)])
def test_runtime_coexistence_and_compensation_wiring(monkeypatch, kind, humidity):
    provider, addresses = FakeAir(), []
    def factory(*, address):
        addresses.append(address)
        return provider
    monkeypatch.setattr('robot.runtime.CCS811Provider', factory)
    environment = SimpleNamespace(start=lambda: None, close=lambda: None,
                                  read=lambda: EnvironmentalReading(23, humidity, 1000))
    async def exercise():
        display = MemoryEyeDisplay()
        runtime = build_runtime(config=RuntimeConfig(environmental_enabled=True,
            environmental_type=kind, ccs811_enabled=True, ccs811_i2c_address='0x5b',
            ccs811_poll_interval_seconds=1), eye_display=display,
            sensor_provider_factory=lambda: environment)
        await runtime.start()
        try:
            for _ in range(200):
                state = runtime.sensor_status()
                expected = EnvironmentalCompensation(23, humidity) if humidity is not None else None
                if state['environmental']['available'] and provider.compensations and provider.compensations[-1] == expected:
                    break
                await asyncio.sleep(.01)
            assert state['environmental']['available'] and state['ccs811']['available']
            assert provider.compensations[-1] == expected
            assert runtime.core.is_running and display.frames
        finally:
            await runtime.stop()
    asyncio.run(exercise())
    assert addresses == [0x5b]
    assert provider.closes == 1


@pytest.mark.parametrize("status", [0x90, 0x98])
def test_reconnect_to_application_does_not_reset_or_repeat_app_start(adapter, status):
    create, bus, _, delays, _ = adapter
    bus.status = status
    provider = create()
    provider.start()
    provider.close()
    provider.start()
    assert not delays
    assert not any(c[0] in {"block", "command"} for c in bus.calls)
    assert bus.mode == 0x10


@pytest.mark.parametrize("stage", ["read HW_ID", "read initial STATUS", "verify APP_START", "verify MEAS_MODE"])
def test_invalid_bus_reads_identify_failing_initialization_phase(adapter, stage):
    create, bus, *_ = adapter
    if stage == "read HW_ID":
        bus.chip = 0xFF
    elif stage == "read initial STATUS":
        bus.status = 0xFF
    elif stage == "verify APP_START":
        def bad_app(*args):
            bus.status = 0xFF
        bus.write_byte = bad_app
    else:
        def bad_mode(*args):
            bus.mode = 0xFF
        bus.write_byte_data = bad_mode
    with pytest.raises((ValueError, OSError), match=stage) as error:
        create().start()
    assert "0xff" in str(error.value) and "0x5a" in str(error.value)
    assert bus.calls[-1] == ('close',)
    assert not any(c[0] == 'block' for c in bus.calls)
