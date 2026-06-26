from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .bluetooth import FitorbBleClient
from .const import (
    CONF_HEALTH_POLL_INTERVAL,
    DEFAULT_HEALTH_POLL_INTERVAL,
    DEFAULT_SUMMARY_POLL_INTERVAL,
    DOMAIN,
)
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
        self.health_poll_interval = timedelta(
            minutes=int(
                entry.options.get(
                    CONF_HEALTH_POLL_INTERVAL,
                    DEFAULT_HEALTH_POLL_INTERVAL.total_seconds() / 60,
                )
            )
        )
        self.last_successful_health_poll: datetime | None = None
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
        include_health = self._health_poll_is_due()
        try:
            base = self.data or self.base_data
            data = await self.client.async_read_current_data(
                base,
                include_health=include_health,
            )
        except Exception as err:
            previous = self.data or self.base_data
            self.async_set_updated_data(
                previous.with_values(available=False, last_error=str(err))
            )
            raise UpdateFailed(str(err)) from err
        updated_at = datetime.now(UTC)
        if include_health:
            self.last_successful_health_poll = updated_at
        return data.with_values(
            available=True,
            last_error=None,
            last_successful_update=updated_at,
        )

    def _health_poll_is_due(self) -> bool:
        """Return whether health polling is due for this refresh."""
        if self.last_successful_health_poll is None:
            return True
        return datetime.now(UTC) - self.last_successful_health_poll >= (
            self.health_poll_interval
        )
