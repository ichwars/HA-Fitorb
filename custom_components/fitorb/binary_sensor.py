from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VERSION
from .coordinator import FitorbDataUpdateCoordinator
from .models import FitorbData


@dataclass(frozen=True, kw_only=True)
class FitorbBinarySensorDescription(BinarySensorEntityDescription):
    """Describe a Fitorb binary sensor."""

    value_fn: Callable[[FitorbData], bool | None]


BINARY_SENSOR_DESCRIPTIONS: dict[str, FitorbBinarySensorDescription] = {
    "is_charging": FitorbBinarySensorDescription(
        key="is_charging",
        translation_key="is_charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.is_charging,
    ),
    "connection_state": FitorbBinarySensorDescription(
        key="connection_state",
        translation_key="connection_state",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.available,
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Fitorb binary sensors."""
    coordinator: FitorbDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        FitorbBinarySensorEntity(coordinator, key)
        for key in BINARY_SENSOR_DESCRIPTIONS
    )


class FitorbBinarySensorEntity(
    CoordinatorEntity[FitorbDataUpdateCoordinator],
    BinarySensorEntity,
):
    """Represent a Fitorb binary sensor."""

    entity_description: FitorbBinarySensorDescription
    _attr_has_entity_name = True

    def __init__(self, coordinator: FitorbDataUpdateCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self.entity_description = BINARY_SENSOR_DESCRIPTIONS[key]
        address = coordinator.base_data.address.replace(":", "").lower()
        self._attr_unique_id = f"{address}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, address)},
            "name": coordinator.base_data.name,
            "manufacturer": "Fitorb",
            "model": "Colmi-compatible Smart Ring",
            "sw_version": VERSION,
        }

    @property
    def available(self) -> bool:
        """Return entity availability."""
        data = self.coordinator.data
        if self.entity_description.key == "connection_state":
            return data is not None
        if data is None:
            return False
        return data.available or self.entity_description.value_fn(data) is not None

    @property
    def is_on(self) -> bool | None:
        """Return the binary sensor state."""
        data = self.coordinator.data
        if data is None:
            return None
        return self.entity_description.value_fn(data)
