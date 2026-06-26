from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .models import FitorbHistoryResult, FitorbHistorySample

_STORE_VERSION = 1


class FitorbHistoryStore:
    """Persist historical sync metadata and dedupe keys for one config entry."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass,
            _STORE_VERSION,
            f"{DOMAIN}_history_{entry_id}",
        )
        self._data: dict[str, Any] = {
            "last_sync": None,
            "last_sample_count": 0,
            "first_sample": None,
            "last_sample": None,
            "last_status": None,
            "unknown_packets": 0,
            "malformed_packets": 0,
            "samples": {},
        }

    @property
    def last_sync(self) -> datetime | None:
        """Return the last history sync timestamp."""
        return _parse_datetime(self._data.get("last_sync"))

    @property
    def last_sample_count(self) -> int:
        """Return total unique samples recorded in the ledger."""
        return int(self._data.get("last_sample_count") or 0)

    @property
    def first_sample(self) -> datetime | None:
        """Return the earliest unique historical sample timestamp."""
        return _parse_datetime(self._data.get("first_sample"))

    @property
    def last_sample(self) -> datetime | None:
        """Return the latest unique historical sample timestamp."""
        return _parse_datetime(self._data.get("last_sample"))

    @property
    def last_status(self) -> str | None:
        """Return the last history sync status."""
        value = self._data.get("last_status")
        return value if isinstance(value, str) else None

    @property
    def unknown_packets(self) -> int:
        """Return unknown packet count from the last history sync."""
        return _parse_int(self._data.get("unknown_packets"))

    @property
    def malformed_packets(self) -> int:
        """Return malformed packet count from the last history sync."""
        return _parse_int(self._data.get("malformed_packets"))

    async def async_load(self) -> None:
        """Load store data from disk."""
        loaded = await self._store.async_load()
        if loaded is not None:
            self._data.update(loaded)
        if not isinstance(self._data.get("samples"), dict):
            self._data["samples"] = {}

    async def async_record_result(
        self,
        result: FitorbHistoryResult,
        synced_at: datetime,
    ) -> tuple[FitorbHistorySample, ...]:
        """Record unique samples from a sync result and persist metadata."""
        samples: dict[str, dict[str, Any]] = self._data.setdefault("samples", {})
        new_samples: list[FitorbHistorySample] = []

        for sample in result.samples:
            key = _sample_key(sample)
            if key in samples:
                continue
            samples[key] = _sample_to_json(sample)
            new_samples.append(sample)

        self._data["last_sync"] = synced_at.astimezone(UTC).isoformat()
        self._data["last_sample_count"] = len(samples)
        self._data["last_status"] = result.status
        self._data["unknown_packets"] = result.unknown_packets
        self._data["malformed_packets"] = result.malformed_packets

        timestamps = [
            _parse_datetime(item.get("timestamp"))
            for item in samples.values()
            if isinstance(item, dict)
        ]
        valid_timestamps = [stamp for stamp in timestamps if stamp is not None]
        self._data["first_sample"] = (
            min(valid_timestamps).isoformat() if valid_timestamps else None
        )
        self._data["last_sample"] = (
            max(valid_timestamps).isoformat() if valid_timestamps else None
        )

        await self._store.async_save(self._data)
        return tuple(new_samples)


def _sample_key(sample: FitorbHistorySample) -> str:
    return "|".join(
        [
            sample.metric.value,
            sample.timestamp.astimezone(UTC).isoformat(),
            str(sample.value),
        ]
    )


def _sample_to_json(sample: FitorbHistorySample) -> dict[str, Any]:
    return {
        "metric": sample.metric.value,
        "timestamp": sample.timestamp.astimezone(UTC).isoformat(),
        "value": sample.value,
        "source_day": sample.source_day.isoformat(),
        "raw_hex": sample.raw_hex,
    }


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
