from __future__ import annotations

from datetime import UTC, datetime
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .bluetooth import FitorbBleClient
from .const import DEFAULT_SUMMARY_POLL_INTERVAL, DOMAIN
from .models import FitorbData

_LOGGER = logging.getLogger(__name__)


class FitorbDataUpdateCoordinator(DataUpdateCoordinator[FitorbData]):
    """Coordinate polling a Fitorb smart ring."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: FitorbBleClient,
    ) -> None:
        self.entry = entry
        self.client = client
        self.base_data = FitorbData(
            address=entry.data[CONF_ADDRESS],
            name=entry.data.get(CONF_NAME, entry.title),
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SUMMARY_POLL_INTERVAL,
        )

    async def _async_update_data(self) -> FitorbData:
        """Fetch data from the ring."""
        try:
            base = self.data or self.base_data
            data = await self.client.async_read_current_data(base)
        except Exception as err:
            previous = self.data or self.base_data
            self.async_set_updated_data(
                previous.with_values(available=False, last_error=str(err))
            )
            raise UpdateFailed(str(err)) from err
        return data.with_values(
            available=True,
            last_error=None,
            last_successful_update=datetime.now(UTC),
        )
