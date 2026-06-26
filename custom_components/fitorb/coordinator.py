from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_NAME, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .bluetooth import FitorbBleClient, FitorbDeviceUnavailable
from .const import (
    CONF_HEALTH_POLL_INTERVAL,
    CONF_HISTORY_LOOKBACK_DAYS,
    CONF_HISTORY_SYNC_INTERVAL,
    DEFAULT_HEALTH_POLL_INTERVAL,
    DEFAULT_HISTORY_LOOKBACK_DAYS,
    DEFAULT_HISTORY_SYNC_INTERVAL,
    DEFAULT_SUMMARY_POLL_INTERVAL,
    DOMAIN,
    HISTORY_OVERLAP_DAYS,
)
from .history_store import FitorbHistoryStore
from .models import FitorbData, FitorbHistoryRequest

_LOGGER = logging.getLogger(__name__)


class FitorbDataUpdateCoordinator(DataUpdateCoordinator[FitorbData]):
    """Coordinate polling a Fitorb smart ring."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: FitorbBleClient,
        history_store: FitorbHistoryStore | None = None,
    ) -> None:
        self.entry = entry
        self.client = client
        self.history_store = history_store or FitorbHistoryStore(hass, entry.entry_id)
        self.health_poll_interval = timedelta(
            minutes=int(
                entry.options.get(
                    CONF_HEALTH_POLL_INTERVAL,
                    DEFAULT_HEALTH_POLL_INTERVAL.total_seconds() / 60,
                )
            )
        )
        self.history_lookback_days = int(
            entry.options.get(CONF_HISTORY_LOOKBACK_DAYS, DEFAULT_HISTORY_LOOKBACK_DAYS)
        )
        self.history_sync_interval = timedelta(
            minutes=int(
                entry.options.get(
                    CONF_HISTORY_SYNC_INTERVAL,
                    DEFAULT_HISTORY_SYNC_INTERVAL.total_seconds() / 60,
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
            update_interval=timedelta(
                minutes=int(
                    entry.options.get(
                        CONF_SCAN_INTERVAL,
                        DEFAULT_SUMMARY_POLL_INTERVAL.total_seconds() / 60,
                    )
                )
            ),
        )

    async def _async_update_data(self) -> FitorbData:
        """Fetch data from the ring."""
        include_health = self._health_poll_is_due()
        try:
            base = self.data or self.base_data
            now = datetime.now(UTC)
            history_request = (
                self._build_history_request(now)
                if self._history_sync_is_due(now)
                else None
            )
            if history_request is None:
                data = await self.client.async_read_current_data(
                    base,
                    include_health=include_health,
                )
                history = None
            else:
                read_result = await self.client.async_read_current_data_with_history(
                    base,
                    include_health=include_health,
                    history_request=history_request,
                )
                data = read_result.data
                history = read_result.history
            if history is not None:
                try:
                    await self.history_store.async_record_result(history, now)
                    data = self._apply_history_store_summary(data)
                except Exception as err:
                    _LOGGER.debug(
                        "Unable to persist Fitorb history sync result: %s",
                        err,
                    )
                    data = self._apply_history_store_summary(data).with_values(
                        last_history_sync=now,
                        last_history_status="error",
                        history_unknown_packets=history.unknown_packets,
                        history_malformed_packets=history.malformed_packets,
                    )
            else:
                data = self._apply_history_store_summary(data)
        except FitorbDeviceUnavailable as err:
            previous = self._apply_history_store_summary(self.data or self.base_data)
            _LOGGER.debug("Fitorb ring is not currently connectable: %s", err)
            return previous.with_values(available=False, last_error=str(err))
        except Exception as err:
            previous = self._apply_history_store_summary(self.data or self.base_data)
            self.async_set_updated_data(
                previous.with_values(available=False, last_error=str(err))
            )
            raise UpdateFailed(str(err)) from err
        updated_at = now
        if include_health and _has_health_value(data):
            self.last_successful_health_poll = updated_at
        elif include_health:
            _LOGGER.debug(
                "Fitorb health poll did not return health values; "
                "will retry on next summary poll"
            )
        return data.with_values(
            available=True,
            last_error=None,
            last_successful_update=updated_at,
        )

    def _apply_history_store_summary(self, data: FitorbData) -> FitorbData:
        """Return data with persisted history summary metadata applied."""
        last_sync = self.history_store.last_sync
        last_status = self.history_store.last_status
        first_sample = self.history_store.first_sample
        last_sample = self.history_store.last_sample
        sample_count = self.history_store.last_sample_count
        unknown_packets = self.history_store.unknown_packets
        malformed_packets = self.history_store.malformed_packets
        if (
            last_sync is None
            and last_status is None
            and first_sample is None
            and last_sample is None
            and sample_count == 0
            and unknown_packets == 0
            and malformed_packets == 0
        ):
            return data
        return data.with_values(
            last_history_sync=last_sync,
            last_history_sample_count=sample_count,
            last_history_status=last_status,
            last_history_first_sample=first_sample,
            last_history_last_sample=last_sample,
            history_unknown_packets=unknown_packets,
            history_malformed_packets=malformed_packets,
        )

    def _history_sync_is_due(self, now: datetime) -> bool:
        """Return whether history sync should run on this update."""
        if self.history_store.last_sync is None:
            return True
        return now - self.history_store.last_sync >= self.history_sync_interval

    def _build_history_request(self, now: datetime) -> FitorbHistoryRequest:
        """Build history request days with a fixed overlap."""
        lookback = max(1, self.history_lookback_days)
        offsets = tuple(range(0, lookback + HISTORY_OVERLAP_DAYS))
        today = now.date()
        days = tuple(today - timedelta(days=offset) for offset in offsets)
        return FitorbHistoryRequest(days=days, day_offsets=offsets)

    def _health_poll_is_due(self) -> bool:
        """Return whether health polling is due for this refresh."""
        if self.last_successful_health_poll is None:
            return True
        return datetime.now(UTC) - self.last_successful_health_poll >= (
            self.health_poll_interval
        )


def _has_health_value(data: FitorbData) -> bool:
    """Return whether a snapshot contains at least one live health value."""
    return (
        data.heart_rate is not None
        or data.spo2 is not None
        or data.stress is not None
    )
