from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant

from .const import DOMAIN


def _redact_address(address: str) -> str:
    parts = address.split(":")
    if len(parts) != 6:
        return "***"
    return ":".join(parts[:3] + ["***"])


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a Fitorb config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data
    return {
        "entry_title": entry.title,
        "address": _redact_address(entry.data[CONF_ADDRESS]),
        "available": data.available if data else False,
        "last_successful_update": data.last_successful_update.isoformat()
        if data and data.last_successful_update
        else None,
        "last_error": data.last_error if data else None,
        "unknown_notifications": data.unknown_notifications if data else 0,
        "malformed_notifications": data.malformed_notifications if data else 0,
    }
