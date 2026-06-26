from __future__ import annotations

from datetime import UTC, datetime
import logging

from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from custom_components.fitorb.const import DOMAIN
from custom_components.fitorb.models import FitorbData
from custom_components.fitorb.sensor import FitorbSensorEntity
from custom_components.fitorb.binary_sensor import FitorbBinarySensorEntity


class FakeCoordinator(DataUpdateCoordinator[FitorbData]):
    def __init__(self, hass: HomeAssistant, data: FitorbData) -> None:
        self.base_data = data
        super().__init__(hass, logging.getLogger(__name__), name=DOMAIN)
        self.async_set_updated_data(data)


def test_battery_sensor_value(hass: HomeAssistant) -> None:
    data = FitorbData(
        address="AA:BB:CC:DD:EE:FF",
        name="Ring",
        available=True,
        battery_level=72,
    )
    coordinator = FakeCoordinator(hass, data)
    entity = FitorbSensorEntity(coordinator, "battery_level")

    assert entity.unique_id == "aabbccddeeff_battery_level"
    assert entity.native_value == 72
    assert entity.native_unit_of_measurement == PERCENTAGE
    assert entity.available is True


def test_last_update_sensor_value(hass: HomeAssistant) -> None:
    stamp = datetime(2026, 6, 26, 1, 2, 3, tzinfo=UTC)
    data = FitorbData(
        address="AA:BB:CC:DD:EE:FF",
        name="Ring",
        available=True,
        last_successful_update=stamp,
    )
    coordinator = FakeCoordinator(hass, data)
    entity = FitorbSensorEntity(coordinator, "last_successful_update")

    assert entity.native_value == stamp


def test_charging_binary_sensor_value(hass: HomeAssistant) -> None:
    data = FitorbData(
        address="AA:BB:CC:DD:EE:FF",
        name="Ring",
        available=True,
        is_charging=True,
    )
    coordinator = FakeCoordinator(hass, data)
    entity = FitorbBinarySensorEntity(coordinator, "is_charging")

    assert entity.unique_id == "aabbccddeeff_is_charging"
    assert entity.is_on is True
