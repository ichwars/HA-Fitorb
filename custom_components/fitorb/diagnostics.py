from __future__ import annotations

import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_MAC_PATTERN = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")


def _redact_address(address: str) -> str:
    separator = ":" if ":" in address else "-"
    parts = address.split(separator)
    if len(parts) != 6:
        return "***"
    return separator.join(parts[:3] + ["***"])


def _redact_last_error(last_error: str | None, configured_address: str) -> str | None:
    """Redact configured and MAC-like addresses from diagnostics errors."""
    if last_error is None:
        return None

    redacted = last_error.replace(
        configured_address,
        _redact_address(configured_address),
    )
    return _MAC_PATTERN.sub(
        lambda match: _redact_address(match.group(0)),
        redacted,
    )


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a Fitorb config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data
    configured_address = entry.data[CONF_ADDRESS]
    return {
        "entry_title": entry.title,
        "address": _redact_address(configured_address),
        "available": data.available if data else False,
        "last_successful_update": data.last_successful_update.isoformat()
        if data and data.last_successful_update
        else None,
        "last_error": _redact_last_error(
            data.last_error if data else None,
            configured_address,
        ),
        "unknown_notifications": data.unknown_notifications if data else 0,
        "malformed_notifications": data.malformed_notifications if data else 0,
    }
