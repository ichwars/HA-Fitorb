from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE, UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FitorbDataUpdateCoordinator
from .models import FitorbData


@dataclass(frozen=True, kw_only=True)
class FitorbSensorDescription(SensorEntityDescription):
    """Describe a Fitorb sensor."""

    value_fn: Callable[[FitorbData], StateType]


SENSOR_DESCRIPTIONS: dict[str, FitorbSensorDescription] = {
    "battery_level": FitorbSensorDescription(
        key="battery_level",
        translation_key="battery_level",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.battery_level,
    ),
    "steps": FitorbSensorDescription(
        key="steps",
        translation_key="steps",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.steps,
    ),
    "calories": FitorbSensorDescription(
        key="calories",
        translation_key="calories",
        native_unit_of_measurement="kcal",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.calories,
    ),
    "distance": FitorbSensorDescription(
        key="distance",
        translation_key="distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.distance,
    ),
    "heart_rate": FitorbSensorDescription(
        key="heart_rate",
        translation_key="heart_rate",
        native_unit_of_measurement="bpm",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.heart_rate,
    ),
    "spo2": FitorbSensorDescription(
        key="spo2",
        translation_key="spo2",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.spo2,
    ),
    "stress": FitorbSensorDescription(
        key="stress",
        translation_key="stress",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.stress,
    ),
    "last_successful_update": FitorbSensorDescription(
        key="last_successful_update",
        translation_key="last_successful_update",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.last_successful_update,
    ),
    "last_history_sync": FitorbSensorDescription(
        key="last_history_sync",
        translation_key="last_history_sync",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.last_history_sync,
    ),
    "last_history_sample_count": FitorbSensorDescription(
        key="last_history_sample_count",
        translation_key="last_history_sample_count",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.last_history_sample_count,
    ),
    "last_history_status": FitorbSensorDescription(
        key="last_history_status",
        translation_key="last_history_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.last_history_status,
    ),
    "last_history_first_sample": FitorbSensorDescription(
        key="last_history_first_sample",
        translation_key="last_history_first_sample",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.last_history_first_sample,
    ),
    "last_history_last_sample": FitorbSensorDescription(
        key="last_history_last_sample",
        translation_key="last_history_last_sample",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.last_history_last_sample,
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Fitorb sensors."""
    coordinator: FitorbDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        FitorbSensorEntity(coordinator, key) for key in SENSOR_DESCRIPTIONS
    )


class FitorbSensorEntity(CoordinatorEntity[FitorbDataUpdateCoordinator], SensorEntity):
    """Represent a Fitorb sensor."""

    entity_description: FitorbSensorDescription
    _attr_has_entity_name = True

    def __init__(self, coordinator: FitorbDataUpdateCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self.entity_description = SENSOR_DESCRIPTIONS[key]
        address = coordinator.base_data.address.replace(":", "").lower()
        self._attr_unique_id = f"{address}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, address)},
            "name": coordinator.base_data.name,
            "manufacturer": "Fitorb",
            "model": "Colmi-compatible Smart Ring",
        }

    @property
    def available(self) -> bool:
        """Return entity availability."""
        data = self.coordinator.data
        return bool(data and data.available)

    @property
    def native_value(self) -> StateType:
        """Return the sensor value."""
        data = self.coordinator.data
        if data is None:
            return None
        return self.entity_description.value_fn(data)
