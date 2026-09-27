"""CCS811 register adapter over optional smbus2, owned by the sensor worker.

Register protocol: ams CCS811 DS000459 v1-06. nWAKE must be held low by
wiring; no GPIO owner, interrupt thread, firmware loader or baseline store.
"""
from __future__ import annotations

import logging
import time

from robot.sensors import AirQualityReading, EnvironmentalCompensation, SensorNotReady

logger = logging.getLogger(__name__)


class CCS811Provider:
    available_measurements = ("eco2_ppm", "tvoc_ppb")
    CONDITIONING_SECONDS = 20 * 60

    def __init__(self, *, address: int, clock=time.monotonic, sleep=time.sleep):
        self._address = address
        self._clock, self._sleep = clock, sleep
        self._bus = None
        self._application = False
        self._started_at = None
        self._compensation_bytes = None

    def _status(self):
        status = self._bus.read_byte_data(self._address, 0x00)
        if status == 0xFF:
            raise OSError("CCS811 invalid STATUS=0xff; I2C communication is unreliable")
        if status & 0x01:
            error_id = self._bus.read_byte_data(self._address, 0xE0)
            raise OSError(f"CCS811 STATUS=0x{status:02x} ERROR_ID=0x{error_id:02x}")
        return status

    def start(self):
        from smbus2 import SMBus

        logger.debug("Initializing CCS811 on I2C bus 1 at 0x%02x", self._address)
        phase = "open bus"
        try:
            self._bus = SMBus(1)
            phase = "read HW_ID"
            chip_id = self._bus.read_byte_data(self._address, 0x20)
            if chip_id != 0x81:
                raise ValueError(f"HW_ID=0x{chip_id:02x}, expected 0x81")
            phase = "read initial STATUS"
            status = self._status()
            logger.debug("CCS811 at 0x%02x: HW_ID=0x%02x STATUS=0x%02x",
                         self._address, chip_id, status)
            if not status & 0x10:
                raise OSError(f"No valid application firmware (STATUS=0x{status:02x})")
            # Normal boot needs APP_START, not SW_RESET. Preserve an already
            # running application on reconnect and never reset a healthy chip.
            if not status & 0x80:
                phase = "APP_START"
                self._bus.write_byte(self._address, 0xF4)
                self._sleep(.01)
                phase = "verify APP_START"
                status = self._status()
                if not status & 0x80:
                    raise OSError(f"Did not enter application mode (STATUS=0x{status:02x})")
            # Fixed mode 1 supplies processed gas readings every second.
            # User poll interval controls host sampling, not device drive mode.
            phase = "set MEAS_MODE"
            self._bus.write_byte_data(self._address, 0x01, 0x10)
            phase = "verify MEAS_MODE"
            status = self._status()
            mode = self._bus.read_byte_data(self._address, 0x01)
            if not status & 0x80 or mode != 0x10:
                raise OSError(f"Unexpected STATUS=0x{status:02x} MEAS_MODE=0x{mode:02x}")
            self._application = True
            self._started_at = self._clock()
            self._compensation_bytes = None
            logger.info("CCS811 initialized at 0x%02x; conditioning for 20 minutes", self._address)
        except Exception as error:
            # Preserve the failed phase even if cleanup also fails.
            try:
                self.close()
            except Exception:
                logger.debug("CCS811 initialization cleanup failed", exc_info=True)
            if isinstance(error, (OSError, ValueError)):
                raise type(error)(f"CCS811 at 0x{self._address:02x}, {phase}: {error}") from error
            raise

    def set_compensation(self, values: EnvironmentalCompensation | None):
        if not self._application:
            raise RuntimeError("CCS811 is not initialized")
        # Explicitly restore datasheet defaults when the source is stale/missing;
        # otherwise the device would retain the last external values forever.
        values = values if values is not None else EnvironmentalCompensation(25, 50)
        humidity = round(values.humidity_percent * 512)
        temperature = round((values.temperature_c + 25) * 512)
        data = (humidity >> 8, humidity & 0xFF, temperature >> 8, temperature & 0xFF)
        if data != self._compensation_bytes:
            self._bus.write_i2c_block_data(self._address, 0x05, list(data))
            self._compensation_bytes = data

    def read(self):
        if not self._application:
            raise RuntimeError("CCS811 is not initialized")
        status = self._status()
        if not status & 0x80:
            raise OSError("CCS811 left application mode")
        warming_up = self._clock() - self._started_at < self.CONDITIONING_SECONDS
        data = None
        if status & 0x08:
            data = self._bus.read_i2c_block_data(self._address, 0x02, 8)
            if len(data) != 8:
                raise OSError("CCS811 returned an incomplete result")
            if data[4] & 0x01:
                raise OSError(f"CCS811 result ERROR_ID=0x{data[5]:02x}")
            if not data[4] & 0x80:
                raise OSError("CCS811 result is not in application mode")
        if warming_up:
            raise SensorNotReady("CCS811 conditioning: readings withheld for 20 minutes", warming_up=True)
        if data is None:
            raise SensorNotReady("CCS811 has no new data")
        reading = AirQualityReading((data[0] << 8) | data[1], (data[2] << 8) | data[3])
        if not 400 <= reading.eco2_ppm <= 29206 or reading.tvoc_ppb > 32768:
            raise ValueError("CCS811 result outside supported range")
        return reading

    def close(self):
        bus, self._bus = self._bus, None
        application, self._application = self._application, False
        self._started_at = self._compensation_bytes = None
        if bus is not None:
            try:
                if application:
                    bus.write_byte_data(self._address, 0x01, 0x00)
            finally:
                bus.close()