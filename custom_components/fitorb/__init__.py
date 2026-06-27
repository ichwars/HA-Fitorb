from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant

from .bluetooth import FitorbBleClient
from .const import DOMAIN, PLATFORMS
from .coordinator import FitorbDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Fitorb from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    client = FitorbBleClient(hass, entry.data[CONF_ADDRESS])
    coordinator = FitorbDataUpdateCoordinator(hass, entry, client)
    await coordinator.history_store.async_load()
    fallback = coordinator._apply_history_store_summary(
        coordinator.data or coordinator.base_data
    )
    coordinator.async_set_updated_data(
        fallback.with_values(
            available=False,
            last_error="Waiting for first Bluetooth update",
        )
    )
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    refresh_task = hass.async_create_task(_async_refresh_after_setup(coordinator))
    entry.async_on_unload(refresh_task.cancel)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Fitorb config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload Fitorb when config entry options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_refresh_after_setup(
    coordinator: FitorbDataUpdateCoordinator,
) -> None:
    """Refresh Fitorb data without blocking config entry setup."""
    try:
        await coordinator.async_request_refresh()
    except Exception as err:
        _LOGGER.debug("Initial Fitorb refresh after setup failed: %s", err)
