from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.const import CONF_ADDRESS, CONF_NAME, CONF_SCAN_INTERVAL
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_HEALTH_POLL_INTERVAL,
    DEFAULT_HEALTH_POLL_INTERVAL,
    DEFAULT_NAME,
    DEFAULT_SUMMARY_POLL_INTERVAL,
    DOMAIN,
)

_MAC_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$", re.IGNORECASE)


def _normalize_address(address: str) -> str:
    return address.strip().upper()


def _is_valid_address(address: str) -> bool:
    return bool(_MAC_RE.match(_normalize_address(address)))


def _default_options() -> dict[str, int]:
    return {
        CONF_SCAN_INTERVAL: int(DEFAULT_SUMMARY_POLL_INTERVAL.total_seconds() / 60),
        CONF_HEALTH_POLL_INTERVAL: int(
            DEFAULT_HEALTH_POLL_INTERVAL.total_seconds() / 60
        ),
    }


class FitorbConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a Fitorb config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle manual setup."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = _normalize_address(user_input[CONF_ADDRESS])
            if not _is_valid_address(address):
                errors[CONF_ADDRESS] = "invalid_address"
            else:
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                name = user_input.get(CONF_NAME) or DEFAULT_NAME
                return self.async_create_entry(
                    title=name,
                    data={CONF_ADDRESS: address, CONF_NAME: name},
                    options=_default_options(),
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): str,
                    vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                }
            ),
            errors=errors,
        )

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle Bluetooth discovery."""
        address = _normalize_address(discovery_info.address)
        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()
        self._discovery = discovery_info
        self.context["title_placeholders"] = {
            "name": discovery_info.name or DEFAULT_NAME
        }
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Confirm Bluetooth discovery."""
        if self._discovery is None:
            return self.async_abort(reason="no_discovery_info")

        address = _normalize_address(self._discovery.address)
        name = self._discovery.name or DEFAULT_NAME
        if user_input is not None:
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=name,
                data={CONF_ADDRESS: address, CONF_NAME: name},
                options=_default_options(),
            )

        return self.async_show_form(step_id="bluetooth_confirm")
