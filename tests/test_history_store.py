from __future__ import annotations

from datetime import UTC, date, datetime
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from custom_components.fitorb.models import (
    FitorbHistoryResult,
    FitorbHistorySample,
    HistoryMetric,
)


def _sample(value: int = 72) -> FitorbHistorySample:
    return FitorbHistorySample(
        metric=HistoryMetric.HEART_RATE,
        timestamp=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
        value=value,
        source_day=date(2026, 6, 26),
        raw_hex="1501",
    )


class _FakeStore:
    _saved: dict[str, dict[str, object]] = {}

    def __init__(self, hass: object, version: int, key: str) -> None:
        self.key = key

    async def async_load(self) -> dict[str, object] | None:
        data = self._saved.get(self.key)
        if data is None:
            return None
        return dict(data)

    async def async_save(self, data: dict[str, object]) -> None:
        self._saved[self.key] = dict(data)


class TestFitorbHistoryStore(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        _FakeStore._saved.clear()
        self._store_patch = patch(
            "custom_components.fitorb.history_store.Store",
            _FakeStore,
        )
        self._store_patch.start()
        self.addAsyncCleanup(self._async_cleanup)

    async def _async_cleanup(self) -> None:
        self._store_patch.stop()

    async def test_history_store_deduplicates_samples(self) -> None:
        from custom_components.fitorb.history_store import FitorbHistoryStore

        store = FitorbHistoryStore(object(), "entry-id")
        await store.async_load()
        result = FitorbHistoryResult(
            samples=(_sample(),),
            status="success",
            requested_days=7,
        )

        first = await store.async_record_result(
            result,
            datetime(2026, 6, 26, 12, 1, tzinfo=UTC),
        )
        second = await store.async_record_result(
            result,
            datetime(2026, 6, 26, 12, 2, tzinfo=UTC),
        )

        assert first == (_sample(),)
        assert second == ()
        assert store.last_sample_count == 1
        assert store.last_sync == datetime(2026, 6, 26, 12, 2, tzinfo=UTC)

    async def test_history_store_tracks_first_and_last_sample(self) -> None:
        from custom_components.fitorb.history_store import FitorbHistoryStore

        store = FitorbHistoryStore(object(), "entry-id")
        await store.async_load()
        sample_a = _sample(72)
        sample_b = FitorbHistorySample(
            metric=HistoryMetric.STRESS,
            timestamp=datetime(2026, 6, 26, 13, 0, tzinfo=UTC),
            value=44,
            source_day=date(2026, 6, 26),
        )

        await store.async_record_result(
            FitorbHistoryResult(
                samples=(sample_b, sample_a),
                status="success",
                requested_days=7,
            ),
            datetime(2026, 6, 26, 13, 1, tzinfo=UTC),
        )

        assert store.first_sample == sample_a.timestamp
        assert store.last_sample == sample_b.timestamp
