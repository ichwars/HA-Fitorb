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


def _iso_or_none(value: Any) -> str | None:
    return value.isoformat() if value else None


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
        "history": {
            "last_sync": _iso_or_none(data.last_history_sync) if data else None,
            "sample_count": data.last_history_sample_count if data else None,
            "status": data.last_history_status if data else None,
            "first_sample": _iso_or_none(data.last_history_first_sample)
            if data
            else None,
            "last_sample": _iso_or_none(data.last_history_last_sample)
            if data
            else None,
            "unknown_packets": data.history_unknown_packets if data else 0,
            "malformed_packets": data.history_malformed_packets if data else 0,
        },
        "sleep": {
            "start": _iso_or_none(data.sleep_start) if data else None,
            "end": _iso_or_none(data.sleep_end) if data else None,
            "duration_minutes": data.sleep_duration_minutes if data else None,
            "asleep_minutes": data.sleep_asleep_minutes if data else None,
            "awake_minutes": data.sleep_awake_minutes if data else None,
            "light_minutes": data.sleep_light_minutes if data else None,
            "deep_minutes": data.sleep_deep_minutes if data else None,
            "rem_minutes": data.sleep_rem_minutes if data else None,
        },
    }
