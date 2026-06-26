from __future__ import annotations

from datetime import UTC, datetime
import logging

import pytest

from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from custom_components.fitorb.binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS,
    FitorbBinarySensorEntity,
)
from custom_components.fitorb.const import DOMAIN
from custom_components.fitorb.models import FitorbData
from custom_components.fitorb.sensor import FitorbSensorEntity, SENSOR_DESCRIPTIONS


class FakeCoordinator(DataUpdateCoordinator[FitorbData]):
    def __init__(self, hass: HomeAssistant, data: FitorbData) -> None:
        self.base_data = data
        super().__init__(hass, logging.getLogger(__name__), name=DOMAIN)
        self.async_set_updated_data(data)


def _sample_data() -> FitorbData:
    return FitorbData(
        address="AA:BB:CC:DD:EE:FF",
        name="Ring",
        available=True,
        battery_level=72,
        is_charging=True,
        steps=1234,
        calories=456,
        distance=789,
        heart_rate=61,
        spo2=97,
        stress=12,
        last_successful_update=datetime(2026, 6, 26, 1, 2, 3, tzinfo=UTC),
        last_history_sync=datetime(2026, 6, 26, 3, 0, tzinfo=UTC),
        last_history_sample_count=24,
        last_history_status="success",
        last_history_first_sample=datetime(2026, 6, 25, 0, 0, tzinfo=UTC),
        last_history_last_sample=datetime(2026, 6, 26, 0, 0, tzinfo=UTC),
    )


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


@pytest.mark.parametrize(
    (
        "key",
        "expected_value",
        "expected_translation_key",
        "expected_unit",
        "expected_device_class",
    ),
    [
        ("battery_level", 72, "battery_level", PERCENTAGE, "battery"),
        ("steps", 1234, "steps", None, None),
        ("calories", 456, "calories", "kcal", None),
        ("distance", 789, "distance", "m", "distance"),
        ("heart_rate", 61, "heart_rate", "bpm", None),
        ("spo2", 97, "spo2", PERCENTAGE, None),
        ("stress", 12, "stress", None, None),
        (
            "last_successful_update",
            datetime(2026, 6, 26, 1, 2, 3, tzinfo=UTC),
            "last_successful_update",
            None,
            "timestamp",
        ),
        (
            "last_history_sync",
            datetime(2026, 6, 26, 3, 0, tzinfo=UTC),
            "last_history_sync",
            None,
            "timestamp",
        ),
        ("last_history_sample_count", 24, "last_history_sample_count", None, None),
        ("last_history_status", "success", "last_history_status", None, None),
        (
            "last_history_first_sample",
            datetime(2026, 6, 25, 0, 0, tzinfo=UTC),
            "last_history_first_sample",
            None,
            "timestamp",
        ),
        (
            "last_history_last_sample",
            datetime(2026, 6, 26, 0, 0, tzinfo=UTC),
            "last_history_last_sample",
            None,
            "timestamp",
        ),
    ],
)
def test_all_sensor_descriptors_map_values_and_metadata(
    hass: HomeAssistant,
    key: str,
    expected_value: object,
    expected_translation_key: str,
    expected_unit: str | None,
    expected_device_class: str | None,
) -> None:
    coordinator = FakeCoordinator(hass, _sample_data())
    entity = FitorbSensorEntity(coordinator, key)
    description = SENSOR_DESCRIPTIONS[key]

    assert entity.unique_id == f"aabbccddeeff_{key}"
    assert entity.native_value == expected_value
    assert entity.entity_description is description
    assert entity.has_entity_name is True
    assert description.translation_key == expected_translation_key
    assert description.native_unit_of_measurement == expected_unit
    assert description.device_class == expected_device_class


@pytest.mark.parametrize(
    ("key", "expected_value", "expected_translation_key", "expected_device_class"),
    [
        ("is_charging", True, "is_charging", "battery_charging"),
        ("connection_state", True, "connection_state", "connectivity"),
    ],
)
def test_all_binary_sensor_descriptors_map_values_and_metadata(
    hass: HomeAssistant,
    key: str,
    expected_value: bool,
    expected_translation_key: str,
    expected_device_class: str,
) -> None:
    coordinator = FakeCoordinator(hass, _sample_data())
    entity = FitorbBinarySensorEntity(coordinator, key)
    description = BINARY_SENSOR_DESCRIPTIONS[key]

    assert entity.unique_id == f"aabbccddeeff_{key}"
    assert entity.is_on is expected_value
    assert entity.entity_description is description
    assert entity.has_entity_name is True
    assert description.translation_key == expected_translation_key
    assert description.device_class == expected_device_class
