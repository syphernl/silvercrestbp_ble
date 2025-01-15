from __future__ import annotations

import logging
import asyncio
from datetime import datetime, timezone

from bleak import BLEDevice
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    establish_connection,
    retry_bluetooth_connection_error,
)
from bluetooth_data_tools import short_address
from bluetooth_sensor_state_data import BluetoothData
from home_assistant_bluetooth import BluetoothServiceInfo
from sensor_state_data import SensorDeviceClass, SensorUpdate, Units
from sensor_state_data.enum import StrEnum

from .const import (
    CHARACTERISTIC_BLOOD_PRESSURE,
    # CHARACTERISTIC_BATTERY,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class SilvercrestBPSensor(StrEnum):

    SYSTOLIC = "systolic"
    DIASTOLIC = "diastolic"
    PULSE = "pulse"
    SIGNAL_STRENGTH = "signal_strength"
    # BATTERY_PERCENT = "battery_percent"
    TIMESTAMP = "timestamp"


class SilvercrestBPBluetoothDeviceData(BluetoothData):
    """Data for SilvercrestBP BLE sensors."""

    def __init__(self) -> None:
        super().__init__()
        self._event = asyncio.Event()

    def _start_update(self, service_info: BluetoothServiceInfo) -> None:
        """Update from BLE advertisement data."""
        _LOGGER.debug("Parsing SilvercrestBP BLE advertisement data: %s", service_info)
        self.set_device_manufacturer("Silvercrest")
        self.set_device_type("Blood Pressure Measurement")
        name = f"{service_info.name} {short_address(service_info.address)}"
        self.set_device_name(name)
        self.set_title(name)

    def poll_needed(
        self, service_info: BluetoothServiceInfo, last_poll: float | None
    ) -> bool:
        """
        This is called every time we get a service_info for a device. It means the
        device is working and online.
        """
        return not last_poll or last_poll > UPDATE_INTERVAL

import logging
from datetime import datetime, timezone

_LOGGER = logging.getLogger(__name__)

    @retry_bluetooth_connection_error()
    def notification_handler(self, _, data) -> None:
        """Helper for command events, parsing and updating sensor data."""
        try:
            # Debug log for raw data received
            _LOGGER.debug("Raw data received from BLE device: %s", data)

            syst = data[2] * 256 + data[1]
            diast = data[4] * 256 + data[3]
            arter = data[6] * 256 + data[5]  # This variable is parsed but not used
            dyear = data[8] * 256 + data[7]
            dmonth = data[9]
            dday = data[10]
            dhour = data[11]
            dminu = data[12]
            puls = data[15] * 256 + data[14]
            user = data[16]  # This variable is parsed but not used

            try:
                datetime_str = f"{dyear}/{dmonth}/{dday} {dhour}:{dminu:0>2}"
                date = datetime.strptime(datetime_str, '%Y/%m/%d %H:%M')
                local_timezone = datetime.now(timezone.utc).astimezone().tzinfo
                self.update_sensor(
                    key=str(SilvercrestBPSensor.TIMESTAMP),
                    native_unit_of_measurement=None,
                    native_value=date.replace(tzinfo=local_timezone),
                    name="Measured Date",
                )
            except Exception as e:
                _LOGGER.error("Failed to parse and update Measured Date: %s", str(e))

            _LOGGER.info(
                "Parsed data from BPM device (systolic: %s, diastolic: %s, pulse: %s)",
                syst, diast, puls
            )

            self.update_sensor(
                key=str(SilvercrestBPSensor.SYSTOLIC),
                native_unit_of_measurement=Units.PRESSURE_MMHG,
                native_value=syst,
                device_class=SensorDeviceClass.PRESSURE,
                name="Systolic",
            )
            self.update_sensor(
                key=str(SilvercrestBPSensor.DIASTOLIC),
                native_unit_of_measurement=Units.PRESSURE_MMHG,
                native_value=diast,
                device_class=SensorDeviceClass.PRESSURE,
                name="Diastolic",
            )
            self.update_sensor(
                key=str(SilvercrestBPSensor.PULSE),
                native_unit_of_measurement="bpm",
                native_value=puls,
                name="Pulse",
            )
        except Exception as e:
            _LOGGER.error("Unexpected error while handling BLE notification: %s", str(e))
        finally:
            self._event.set()

    async def async_poll(self, ble_device: BLEDevice) -> SensorUpdate:
        """
        Poll the device to retrieve any values we can't get from passive listening.
        """
        _LOGGER.debug("Connecting to BLE device: %s", ble_device.address)
        client = await establish_connection(
            BleakClientWithServiceCache, ble_device, ble_device.address
        )
        try:
            await client.start_notify(
                CHARACTERISTIC_BLOOD_PRESSURE, self.notification_handler
            )
        except Exception as e:
            _LOGGER.error("Failed to start notify on BLE device %s: %s", ble_device.address, str(e))

        # battery_char = client.services.get_characteristic(CHARACTERISTIC_BATTERY)
        # battery_payload = await client.read_gatt_char(battery_char)
        # self.update_sensor(
        #     key=str(SilvercrestBPSensor.BATTERY_PERCENT),
        #     native_unit_of_measurement=Units.PERCENTAGE,
        #     native_value=battery_payload[0],
        #     device_class=SensorDeviceClass.BATTERY,
        #     name="Battery",
        # )

        # Wait to see if a callback comes in.
        try:
            # Wait to see if a callback comes in within 15 seconds.
            await asyncio.wait_for(self._event.wait(), timeout=15)
        except asyncio.TimeoutError:
            _LOGGER.warning("Timeout while waiting for command data from BLE device.")
        except Exception as e:
            _LOGGER.error("Unexpected error while waiting for BLE response: %s", str(e))
        finally:
            try:
                await client.stop_notify(CHARACTERISTIC_BLOOD_PRESSURE)
            except Exception as e:
                _LOGGER.error("Failed to stop notification on BLE device: %s", str(e))
            try:
                await client.disconnect()
            except Exception as e:
                _LOGGER.error("Failed to disconnect from BLE device: %s", str(e))
            _LOGGER.debug("Disconnected from active Bluetooth client")
        return self._finish_update()