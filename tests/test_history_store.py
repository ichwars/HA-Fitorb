from __future__ import annotations

import copy
import json
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
        return json.loads(json.dumps(data))

    async def async_save(self, data: dict[str, object]) -> None:
        self._saved[self.key] = copy.deepcopy(data)


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

    async def test_history_store_deduplicates_samples_across_reload(self) -> None:
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
        reloaded_store = FitorbHistoryStore(object(), "entry-id")
        await reloaded_store.async_load()
        second = await reloaded_store.async_record_result(
            result,
            datetime(2026, 6, 26, 12, 2, tzinfo=UTC),
        )

        assert first == (_sample(),)
        assert second == ()
        assert reloaded_store.last_sample_count == 1
        assert reloaded_store.last_sync == datetime(2026, 6, 26, 12, 2, tzinfo=UTC)
        assert reloaded_store.first_sample == _sample().timestamp
        assert reloaded_store.last_sample == _sample().timestamp

    async def test_history_store_reloads_serialized_metadata(self) -> None:
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

        persisted = _FakeStore._saved["fitorb_history_entry-id"]
        assert isinstance(persisted["samples"], dict)
        assert all(isinstance(key, str) for key in persisted["samples"])
        assert all(isinstance(item, dict) for item in persisted["samples"].values())

        reloaded_store = FitorbHistoryStore(object(), "entry-id")
        await reloaded_store.async_load()

        assert reloaded_store.first_sample == sample_a.timestamp
        assert reloaded_store.last_sample == sample_b.timestamp
        assert reloaded_store.last_sync == datetime(2026, 6, 26, 13, 1, tzinfo=UTC)
        assert reloaded_store.last_sample_count == 2

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

    async def test_history_store_ignores_invalid_persisted_shapes(self) -> None:
        from custom_components.fitorb.history_store import FitorbHistoryStore

        _FakeStore._saved["fitorb_history_entry-id"] = {
            "last_sync": 123,
            "first_sample": "not-a-datetime",
            "last_sample": None,
            "last_sample_count": 4,
            "samples": ["bad-shape"],
        }

        store = FitorbHistoryStore(object(), "entry-id")
        await store.async_load()

        assert store.last_sync is None
        assert store.first_sample is None
        assert store.last_sample is None
        assert store.last_sample_count == 4
        assert store._data["samples"] == {}
