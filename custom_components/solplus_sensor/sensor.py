"""Platform for lock integration."""
from __future__ import annotations

import logging
import voluptuous as vol
from typing import Final, Any
import homeassistant.helpers.config_validation as cv
from homeassistant.components.sensor import (
    PLATFORM_SCHEMA,
    SensorDeviceClass,
    RestoreSensor,
    SensorStateClass,
)
from homeassistant.const import (
    CONF_IP_ADDRESS,
    CONF_NAME,
    CONF_DEVICES,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback, PlatformNotReady
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

import requests
import itertools
from typing import Literal
import typing_extensions
from datetime import datetime, date, timedelta
import re

_LOGGER = logging.getLogger(__name__)

DOMAIN: Final = "solplus_sensor"
VOLT: Final = UnitOfElectricPotential.VOLT
WATT: Final = UnitOfPower.WATT
kWh: Final = UnitOfEnergy.KILO_WATT_HOUR

# Validation of the user's configuration
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_DEVICES, default={}): vol.Schema(
            {
                cv.string: {
                    vol.Required(CONF_NAME): cv.string,
                    vol.Required(CONF_IP_ADDRESS): cv.string,
                }
            }
        ),
    }
)


def setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    # Assign configuration variables.
    # The configuration check takes care they are present.

    devices = []
    for device_id, device_config in config[CONF_DEVICES].items():
        name = device_config[CONF_NAME]
        ip_address = device_config[CONF_IP_ADDRESS]

        inverter = SOLPLUSInverter(hass, device_id, name, ip_address)

        # Verify that passed in configuration works
        if not inverter.assert_can_connect():
            raise PlatformNotReady(
                f"Could not connect to SOLPLUS Inverter on ip: {ip_address}"
            )

        _LOGGER.info(f"appended device")

        # append to devices array
        devices.append(inverter)

    _LOGGER.info(f"#devices {len(devices)}")

    # Add entities
    add_entities(
        InverterSensor(inverter, sensor_type)
        for inverter, sensor_type in itertools.product(
            devices,
            typing_extensions.get_args(
                Literal["energy", "dc_voltage", "ac_voltage", "power"]
            ),
        )
    )


class SOLPLUSInverter:
    """Controls Connection to SOLPLUS Inverter"""

    def __init__(self, hass: HomeAssistant, device_id, name, ip_address) -> None:
        self._hass = hass
        self._device_id = device_id
        self._name = name
        self._ip_address = ip_address
        self._last_updated_at = datetime.min
        self._values = {
            "energy": 0,
            "dc_voltage": 0,
            "ac_voltage": 0,
            "power": 0,
        }

    async def assert_can_connect(self) -> bool:
        ok, response = await self.request()

        if ok:
            _LOGGER.info(f"Asserted that HA can connect to Inverter")
            return True

        return False

    async def get_values(self):
        if self._last_updated_at < (datetime.now() - timedelta(minutes=1)):
            success, new_values = await self.request()

            if success:
                self._values["energy"] = new_values["energy"]
                self._values["dc_voltage"] = new_values["dc_voltage"]
                self._values["ac_voltage"] = new_values["ac_voltage"]
                self._values["power"] = new_values["power"]
                self._last_updated_at = datetime.now()

            return success, self._values

        return (
            self._last_updated_at >= (datetime.now() - timedelta(seconds=20))
        ), self._values

    async def request(self):
        try:
            r = await self._hass.async_add_executor_job(
                target=requests.get, url=f"http://{self._ip_address}/", timeout=2
            )  #                     ^^ error should not be problematic, this SHOULD be inserted correctly into args
        except requests.exceptions.ConnectTimeout:
            return False, {}

        if r.status_code != 200:
            _LOGGER.error(
                f"Could connect to Inverter but returned status code {r.status_code}"
            )
            return False, {}

        return self.parseHTML(html=r.text)

    def parseHTML(self, html: str):
        response = {
            "energy": 0,
            "dc_voltage": 0,
            "ac_voltage": 0,
            "power": 0,
        }

        try:
            result = re.search(r"<li>Energie Tag:\s*([\d.,]+)\s*kWh", html)
            if result is None:
                _LOGGER.error(f"HTML was recieved, but HTML parsing failed.")
                return False, {}
            response["energy"] = int(result.group(1).replace(".", "").replace(",", ""))

            result = re.search(r"<b>Leistung AC:\s*([\d.,]+)\s*Watt<\/b>", html)
            if result is None:
                _LOGGER.error(f"HTML was recieved, but HTML parsing failed.")
                return False, {}
            response["power"] = int(result.group(1).replace(".", "").replace(",", ""))

            result = re.search(r"<b>Netzspannung:\s*([\d.,]+)\s*Volt<\/b>", html)
            if result is None:
                _LOGGER.error(f"HTML was recieved, but HTML parsing failed.")
                return False, {}
            response["ac_voltage"] = int(
                result.group(1).replace(".", "").replace(",", "")
            )

            result = re.search(r"<b>Gleichspannung:\s*([\d.,]+)\s*Volt<\/b>", html)
            if result is None:
                _LOGGER.error(f"HTML was recieved, but HTML parsing failed.")
                return False, {}
            response["dc_voltage"] = int(
                result.group(1).replace(".", "").replace(",", "")
            )
        except Exception as ex:
            _LOGGER.error(
                f"HTML parsing failed due to exception {type(ex).__name__}, {str(ex.args)}"
            )
            return False, {}

        return True, response


class InverterSensor(RestoreSensor):
    """Control Representation of a sensor measuring some property of the inverter"""

    name_additions = {
        "energy": "Energy",
        "dc_voltage": "DC Voltage",
        "ac_voltage": "AC Voltage",
        "power": "Power",
    }

    def __init__(
        self,
        inverter: SOLPLUSInverter,
        sensor_type: Literal["energy", "dc_voltage", "ac_voltage", "power"],
    ) -> None:
        """Initialize a Sensor for the inverter"""
        self._inverter = inverter
        self._device_id = inverter._device_id + "_" + sensor_type
        self._name = inverter._name + " " + self.name_additions[sensor_type]
        self._sensor_type = sensor_type

        self._native_value = 0
        self._store_last_reset = datetime.min

        self._has_loaded_once = False  # for RestoreSensor features

        self._attr_suggested_display_precision = 0
        match self._sensor_type:
            case "energy":
                self._attr_device_class = SensorDeviceClass.ENERGY
                self._attr_state_class = SensorStateClass.TOTAL_INCREASING
                self.attr_native_unit_of_measurement = kWh
            case "dc_voltage":
                self._attr_device_class = SensorDeviceClass.VOLTAGE
                self._attr_state_class = SensorStateClass.MEASUREMENT
                self.attr_native_unit_of_measurement = VOLT
            case "ac_voltage":
                self._attr_device_class = SensorDeviceClass.VOLTAGE
                self._attr_state_class = SensorStateClass.MEASUREMENT
                self.attr_native_unit_of_measurement = VOLT
            case "power":
                self._attr_device_class = SensorDeviceClass.POWER
                self._attr_state_class = SensorStateClass.MEASUREMENT
                self.attr_native_unit_of_measurement = WATT

    @property
    def name(self) -> str:
        return self._name

    @property
    def native_value(self):
        if self._sensor_type == "energy":
            if (
                self._store_last_reset < self.last_reset
            ):  # new day. reset energy at 00:00 o'clock
                self._native_value = 0
                self._store_last_reset = self.last_reset

        return self._native_value

    @property
    def last_reset(self):
        if self._sensor_type == "energy":
            return datetime.combine(
                date.today(), datetime.min.time()
            )  # "TOTAL_INCREASING" Sensor

        return datetime.now()  # "MEASUREMENT" Sensors

    async def async_update(self):
        is_fresh_value, measurement = await self._inverter.get_values()

        if not self._has_loaded_once:
            # reset state from memory. Only important for if meter is not reachable and `sensor_type` == "energy"
            if (
                last_sensor_data := await self.async_get_last_sensor_data()
            ) is not None:
                self._store_last_reset = (
                    last_sensor_data.last_reset
                )  #                     ^^ error should not be problematic, this SHOULD be there
                self._native_value = last_sensor_data.native_value
            self._has_loaded_once = True

        match self._sensor_type:
            case "dc_voltage":
                self._native_value = measurement["dc_voltage"]
            case "ac_voltage":
                self._native_value = measurement["ac_voltage"]
            case "power":
                self._native_value = measurement["power"]
            case "energy":
                if is_fresh_value:
                    self._native_value = measurement["energy"]
