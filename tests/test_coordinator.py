from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from homeassistant.const import CONF_ADDRESS, CONF_NAME, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.fitorb as fitorb_init
from custom_components.fitorb.bluetooth import (
    FitorbBleClient,
    FitorbDeviceUnavailable,
    FitorbResponseTimeout,
)
from custom_components.fitorb.const import (
    CMD_NOTIFY_CHAR_UUID,
    CMD_WRITE_CHAR_UUID,
    DEFAULT_SUMMARY_POLL_INTERVAL,
    DOMAIN,
    RAW_NOTIFY_CHAR_UUID,
    RAW_WRITE_CHAR_UUID,
)
from custom_components.fitorb.coordinator import FitorbDataUpdateCoordinator
from custom_components.fitorb.models import (
    FitorbData,
    FitorbHistoryRequest,
    FitorbHistoryResult,
    FitorbHistorySample,
    FitorbReadResult,
    FitorbSleepSummary,
    HistoryMetric,
    NotificationKind,
)


class FakeRingClient:
    def __init__(
        self,
        data: FitorbData | None = None,
        err: Exception | None = None,
        read_result: FitorbReadResult | None = None,
    ) -> None:
        self.data = data
        self.err = err
        self.read_result = read_result
        self.calls = 0
        self.include_health_calls: list[bool] = []
        self.history_requests: list[FitorbHistoryRequest | None] = []

    async def async_read_current_data_with_history(
        self,
        base: FitorbData,
        *,
        include_health: bool = True,
        history_request: FitorbHistoryRequest | None = None,
    ) -> FitorbReadResult:
        self.calls += 1
        self.include_health_calls.append(include_health)
        self.history_requests.append(history_request)
        if self.err is not None:
            raise self.err
        if self.read_result is not None:
            return self.read_result
        assert self.data is not None
        return FitorbReadResult(data=self.data)

    async def async_read_current_data(
        self, base: FitorbData, *, include_health: bool = True
    ) -> FitorbData:
        return (
            await self.async_read_current_data_with_history(
                base,
                include_health=include_health,
                history_request=None,
            )
        ).data


class FakeHistoryStore:
    def __init__(self) -> None:
        self.last_sync = None
        self.last_sample_count = 0
        self.first_sample = None
        self.last_sample = None
        self.last_status = None
        self.unknown_packets = 0
        self.malformed_packets = 0
        self.sleep_summary = None
        self.recorded_results: list[FitorbHistoryResult] = []

    async def async_load(self) -> None:
        return None

    async def async_record_result(
        self,
        result: FitorbHistoryResult,
        synced_at: datetime,
    ) -> tuple[FitorbHistorySample, ...]:
        self.last_sync = synced_at
        self.last_sample_count += len(result.samples)
        self.first_sample = result.first_sample
        self.last_sample = result.last_sample
        self.last_status = result.status
        self.unknown_packets = result.unknown_packets
        self.malformed_packets = result.malformed_packets
        self.sleep_summary = result.sleep_summary
        self.recorded_results.append(result)
        return result.samples


@pytest.fixture
def entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain="fitorb",
        title="Ring",
        data={CONF_ADDRESS: "AA:BB:CC:DD:EE:FF", CONF_NAME: "Ring"},
        source="user",
        entry_id="entry-id",
        unique_id="AA:BB:CC:DD:EE:FF",
        options={},
    )


async def test_coordinator_updates_snapshot(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    data = FitorbData(
        address="AA:BB:CC:DD:EE:FF",
        name="Ring",
        available=True,
        steps=123,
    )
    client = FakeRingClient(data=data)
    coordinator = FitorbDataUpdateCoordinator(hass, entry, client)

    result = await coordinator._async_update_data()

    assert result.available is True
    assert result.steps == 123
    assert result.last_successful_update is not None
    assert result.last_successful_update.tzinfo is UTC


async def test_coordinator_wraps_ble_errors(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    client = FakeRingClient(err=TimeoutError("ring timeout"))
    coordinator = FitorbDataUpdateCoordinator(hass, entry, client)

    with pytest.raises(UpdateFailed, match="ring timeout"):
        await coordinator._async_update_data()


async def test_coordinator_marks_entry_unavailable_on_client_timeout(
    hass: HomeAssistant,
    entry: MockConfigEntry,
) -> None:
    client = FakeRingClient(
        err=FitorbResponseTimeout(
            "Timed out waiting for Fitorb battery response"
        )
    )
    coordinator = FitorbDataUpdateCoordinator(hass, entry, client)

    with pytest.raises(
        UpdateFailed,
        match="Timed out waiting for Fitorb battery response",
    ):
        await coordinator._async_update_data()

    assert coordinator.data is not None
    assert coordinator.data.available is False
    assert (
        coordinator.data.last_error
        == "Timed out waiting for Fitorb battery response"
    )


async def test_coordinator_keeps_transient_device_unavailable_quiet(
    hass: HomeAssistant,
    entry: MockConfigEntry,
) -> None:
    client = FakeRingClient(
        err=FitorbDeviceUnavailable("No connectable Bluetooth path to ring")
    )
    coordinator = FitorbDataUpdateCoordinator(hass, entry, client)
    coordinator.async_set_updated_data(
        FitorbData(
            address="AA:BB:CC:DD:EE:FF",
            name="Ring",
            available=True,
            heart_rate=89,
            spo2=97,
            stress=44,
        )
    )

    result = await coordinator._async_update_data()

    assert result.available is False
    assert result.heart_rate == 89
    assert result.spo2 == 97
    assert result.stress == 44
    assert result.last_error == "No connectable Bluetooth path to ring"


async def test_coordinator_requests_health_on_first_successful_update(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    data = FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring", steps=123)
    client = FakeRingClient(data=data)
    coordinator = FitorbDataUpdateCoordinator(hass, entry, client)

    await coordinator._async_update_data()

    assert client.include_health_calls == [True]


async def test_coordinator_skips_health_when_not_due(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    data = FitorbData(
        address="AA:BB:CC:DD:EE:FF",
        name="Ring",
        steps=123,
        heart_rate=72,
    )
    client = FakeRingClient(data=data)
    coordinator = FitorbDataUpdateCoordinator(hass, entry, client)

    first = await coordinator._async_update_data()
    coordinator.async_set_updated_data(first)

    second = await coordinator._async_update_data()

    assert second.last_successful_update is not None
    assert client.include_health_calls == [True, False]


async def test_coordinator_retries_health_until_a_value_is_observed(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    data = FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring", steps=123)
    client = FakeRingClient(data=data)
    coordinator = FitorbDataUpdateCoordinator(hass, entry, client)

    first = await coordinator._async_update_data()
    coordinator.async_set_updated_data(first)

    await coordinator._async_update_data()

    assert coordinator.last_successful_health_poll is None
    assert client.include_health_calls == [True, True]


async def test_coordinator_uses_configured_summary_poll_interval(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain="fitorb",
        title="Ring",
        data={CONF_ADDRESS: "AA:BB:CC:DD:EE:FF", CONF_NAME: "Ring"},
        source="user",
        entry_id="entry-id",
        unique_id="AA:BB:CC:DD:EE:FF",
        options={CONF_SCAN_INTERVAL: 9},
    )
    client = FakeRingClient(
        data=FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring")
    )

    coordinator = FitorbDataUpdateCoordinator(hass, entry, client)

    assert coordinator.update_interval != DEFAULT_SUMMARY_POLL_INTERVAL
    assert coordinator.update_interval.total_seconds() == 9 * 60


async def test_coordinator_requests_history_when_due(
    hass: HomeAssistant,
    entry: MockConfigEntry,
) -> None:
    sample = FitorbHistorySample(
        metric=HistoryMetric.HEART_RATE,
        timestamp=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
        value=72,
        source_day=date(2026, 6, 26),
    )
    history = FitorbHistoryResult(
        samples=(sample,),
        status="success",
        requested_days=7,
        first_sample=sample.timestamp,
        last_sample=sample.timestamp,
    )
    client = FakeRingClient(
        read_result=FitorbReadResult(
            data=FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring", available=True),
            history=history,
        )
    )
    store = FakeHistoryStore()
    coordinator = FitorbDataUpdateCoordinator(hass, entry, client, history_store=store)

    result = await coordinator._async_update_data()

    assert client.history_requests[0] is not None
    assert client.history_requests[0].day_offsets[0] == 0
    assert result.last_history_status == "success"
    assert result.last_history_sample_count == 1


async def test_coordinator_skips_history_when_not_due(
    hass: HomeAssistant,
    entry: MockConfigEntry,
) -> None:
    client = FakeRingClient(
        data=FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring", available=True)
    )
    store = FakeHistoryStore()
    store.last_sync = datetime.now(UTC)
    coordinator = FitorbDataUpdateCoordinator(hass, entry, client, history_store=store)

    await coordinator._async_update_data()

    assert client.history_requests == [None]


async def test_coordinator_rehydrates_persisted_history_when_not_due(
    hass: HomeAssistant,
    entry: MockConfigEntry,
) -> None:
    first_sample = datetime(2026, 6, 25, 6, 0, tzinfo=UTC)
    last_sample = datetime(2026, 6, 26, 6, 0, tzinfo=UTC)
    client = FakeRingClient(
        data=FitorbData(
            address="AA:BB:CC:DD:EE:FF",
            name="Ring",
            available=True,
            steps=123,
        )
    )
    store = FakeHistoryStore()
    store.last_sync = datetime.now(UTC)
    store.last_sample_count = 42
    store.first_sample = first_sample
    store.last_sample = last_sample
    store.last_status = "success"
    store.unknown_packets = 2
    store.malformed_packets = 1
    store.sleep_summary = FitorbSleepSummary(
        source_day=date(2026, 6, 26),
        start=datetime(2026, 6, 26, 23, 0, tzinfo=UTC),
        end=datetime(2026, 6, 27, 5, 8, tzinfo=UTC),
        duration_minutes=368,
        asleep_minutes=363,
        awake_minutes=5,
        light_minutes=180,
        deep_minutes=135,
        rem_minutes=48,
    )
    coordinator = FitorbDataUpdateCoordinator(hass, entry, client, history_store=store)

    result = await coordinator._async_update_data()

    assert client.history_requests == [None]
    assert result.steps == 123
    assert result.last_history_sync == store.last_sync
    assert result.last_history_sample_count == 42
    assert result.last_history_status == "success"
    assert result.last_history_first_sample == first_sample
    assert result.last_history_last_sample == last_sample
    assert result.history_unknown_packets == 2
    assert result.history_malformed_packets == 1
    assert result.sleep_duration_minutes == 368
    assert result.sleep_asleep_minutes == 363
    assert result.sleep_light_minutes == 180
    assert result.sleep_deep_minutes == 135
    assert result.sleep_rem_minutes == 48
    assert result.sleep_awake_minutes == 5


async def test_coordinator_rehydrates_persisted_history_when_unavailable(
    hass: HomeAssistant,
    entry: MockConfigEntry,
) -> None:
    first_sample = datetime(2026, 6, 25, 6, 0, tzinfo=UTC)
    last_sample = datetime(2026, 6, 26, 6, 0, tzinfo=UTC)
    client = FakeRingClient(
        err=FitorbDeviceUnavailable("No connectable Bluetooth path to ring")
    )
    store = FakeHistoryStore()
    store.last_sync = datetime.now(UTC)
    store.last_sample_count = 42
    store.first_sample = first_sample
    store.last_sample = last_sample
    store.last_status = "success"
    coordinator = FitorbDataUpdateCoordinator(hass, entry, client, history_store=store)

    result = await coordinator._async_update_data()

    assert result.available is False
    assert result.last_history_sync == store.last_sync
    assert result.last_history_sample_count == 42
    assert result.last_history_status == "success"
    assert result.last_history_first_sample == first_sample
    assert result.last_history_last_sample == last_sample


def _battery_notification(level: int = 88, charging: bool = False) -> bytes:
    payload = bytearray(16)
    payload[0] = 0x03
    payload[1] = level
    payload[2] = 1 if charging else 0
    return bytes(payload)


def _activity_notification(
    *,
    steps: int = 123,
    calories: int = 4,
    distance: int = 567,
) -> bytes:
    payload = bytearray(16)
    payload[0] = 0x73
    payload[1] = 0x12
    payload[2] = (steps >> 16) & 0xFF
    payload[3] = (steps >> 8) & 0xFF
    payload[4] = steps & 0xFF
    raw_calories = calories * 1000
    payload[5] = (raw_calories >> 16) & 0xFF
    payload[6] = (raw_calories >> 8) & 0xFF
    payload[7] = raw_calories & 0xFF
    payload[8] = (distance >> 16) & 0xFF
    payload[9] = (distance >> 8) & 0xFF
    payload[10] = distance & 0xFF
    return bytes(payload)


def _health_notification(kind: int, *, running: bool, value: int = 0) -> bytes:
    payload = bytearray(16)
    payload[0] = 0x69
    payload[1] = kind
    payload[2] = 0x01
    payload[3] = 0x00 if running else value
    return bytes(payload)


def _unknown_notification() -> bytes:
    payload = bytearray(16)
    payload[0] = 0xFF
    return bytes(payload)


def _units_preference_notification() -> bytes:
    payload = bytearray(16)
    payload[0] = 0x0A
    payload[1] = 0x02
    payload[15] = 0x0C
    return bytes(payload)


def _malformed_notification() -> bytes:
    return bytes([0x03, 0x01, 0x00])


def _test_client() -> FitorbBleClient:
    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    return FitorbBleClient(hass, "AA:BB:CC:DD:EE:FF", response_timeout=0.2)


async def test_ble_client_counts_unknown_notifications_without_failing() -> None:
    client = _test_client()
    queue: asyncio.Queue[bytes] = asyncio.Queue()
    await queue.put(_unknown_notification())
    await queue.put(_battery_notification(level=91))
    snapshot = FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring")

    updated = await client._drain_until_expected(
        queue,
        snapshot,
        expected_kind=NotificationKind.BATTERY,
    )

    assert updated.unknown_notifications == 1
    assert updated.battery_level == 91


async def test_ble_client_ignores_units_preference_ack() -> None:
    client = _test_client()
    queue: asyncio.Queue[bytes] = asyncio.Queue()
    await queue.put(_units_preference_notification())
    await queue.put(_battery_notification(level=91))
    snapshot = FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring")

    updated = await client._drain_until_expected(
        queue,
        snapshot,
        expected_kind=NotificationKind.BATTERY,
    )

    assert updated.unknown_notifications == 0
    assert updated.battery_level == 91


async def test_ble_client_counts_malformed_notifications_separately() -> None:
    client = _test_client()
    queue: asyncio.Queue[bytes] = asyncio.Queue()
    await queue.put(_malformed_notification())
    await queue.put(_unknown_notification())
    await queue.put(_battery_notification(level=91))
    snapshot = FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring")

    updated = await client._drain_until_expected(
        queue,
        snapshot,
        expected_kind=NotificationKind.BATTERY,
    )

    assert updated.malformed_notifications == 1
    assert updated.unknown_notifications == 1
    assert updated.battery_level == 91


async def test_ble_client_treats_out_of_connection_slots_as_unavailable() -> None:
    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    client = FitorbBleClient(hass, "AA:BB:CC:DD:EE:FF", response_timeout=0.05)

    with (
        patch(
            (
                "custom_components.fitorb.bluetooth.bluetooth"
                ".async_ble_device_from_address"
            ),
            return_value=object(),
        ),
        patch(
            "custom_components.fitorb.bluetooth.establish_connection",
            AsyncMock(
                side_effect=Exception(
                    "No backend with an available connection slot that can "
                    "reach address AA:BB:CC:DD:EE:FF was found"
                )
            ),
        ),
    ):
        with pytest.raises(
            FitorbDeviceUnavailable,
            match="available connection slot",
        ):
            await client.async_read_current_data(
                FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring")
            )


async def test_ble_client_treats_missing_command_notify_as_unavailable() -> None:
    class FakeBleakClient:
        async def start_notify(self, _uuid, _handler) -> None:
            raise Exception(
                "Characteristic 6e400003-b5a3-f393-e0a9-e50e24dcca9e "
                "was not found!"
            )

        async def stop_notify(self, _uuid) -> None:
            raise AssertionError("stop_notify should not run before start_notify")

        async def disconnect(self) -> None:
            return None

    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    client = FitorbBleClient(hass, "AA:BB:CC:DD:EE:FF", response_timeout=0.05)

    with (
        patch(
            (
                "custom_components.fitorb.bluetooth.bluetooth"
                ".async_ble_device_from_address"
            ),
            return_value=object(),
        ),
        patch(
            "custom_components.fitorb.bluetooth.establish_connection",
            AsyncMock(return_value=FakeBleakClient()),
        ),
    ):
        with pytest.raises(
            FitorbDeviceUnavailable,
            match="6e400003-b5a3-f393-e0a9-e50e24dcca9e",
        ):
            await client.async_read_current_data(
                FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring")
            )


async def test_ble_client_battery_returns_after_expected_response() -> None:
    client = _test_client()
    queue: asyncio.Queue[bytes] = asyncio.Queue()
    await queue.put(_battery_notification(level=77))
    await queue.put(_activity_notification(steps=999))
    snapshot = FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring")

    updated = await client._drain_until_expected(
        queue,
        snapshot,
        expected_kind=NotificationKind.BATTERY,
    )

    assert updated.battery_level == 77
    assert queue.qsize() == 1


async def test_ble_client_activity_returns_after_expected_response() -> None:
    client = _test_client()
    queue: asyncio.Queue[bytes] = asyncio.Queue()
    await queue.put(_activity_notification(steps=321))
    await queue.put(_battery_notification(level=44))
    snapshot = FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring")

    updated = await client._drain_until_expected(
        queue,
        snapshot,
        expected_kind=NotificationKind.ACTIVITY,
    )

    assert updated.steps == 321
    assert queue.qsize() == 1


async def test_ble_client_keeps_battery_when_activity_times_out() -> None:
    class FakeBleakClient:
        def __init__(self) -> None:
            self.handler = None

        async def start_notify(self, _uuid, handler) -> None:
            self.handler = handler

        async def write_gatt_char(self, _uuid, payload: bytes) -> None:
            if payload[0] == 0x03:
                assert self.handler is not None
                self.handler(1, bytearray(_battery_notification(level=82)))

        async def stop_notify(self, _uuid) -> None:
            return None

        async def disconnect(self) -> None:
            return None

    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    client = FitorbBleClient(
        hass,
        "AA:BB:CC:DD:EE:FF",
        response_timeout=0.05,
    )

    with (
        patch(
            (
                "custom_components.fitorb.bluetooth.bluetooth"
                ".async_ble_device_from_address"
            ),
            return_value=object(),
        ),
        patch(
            "custom_components.fitorb.bluetooth.establish_connection",
            AsyncMock(return_value=FakeBleakClient()),
        ),
    ):
        updated = await client.async_read_current_data(
            FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring"),
            include_health=False,
        )

    assert updated.available is True
    assert updated.battery_level == 82
    assert updated.steps is None


async def test_ble_client_keeps_battery_when_health_times_out() -> None:
    class FakeBleakClient:
        def __init__(self) -> None:
            self.handler = None

        async def start_notify(self, _uuid, handler) -> None:
            self.handler = handler

        async def write_gatt_char(self, _uuid, payload: bytes) -> None:
            if payload[0] == 0x03:
                assert self.handler is not None
                self.handler(1, bytearray(_battery_notification(level=82)))

        async def stop_notify(self, _uuid) -> None:
            return None

        async def disconnect(self) -> None:
            return None

    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    client = FitorbBleClient(
        hass,
        "AA:BB:CC:DD:EE:FF",
        response_timeout=0.05,
    )

    with (
        patch(
            (
                "custom_components.fitorb.bluetooth.bluetooth"
                ".async_ble_device_from_address"
            ),
            return_value=object(),
        ),
        patch(
            "custom_components.fitorb.bluetooth.establish_connection",
            AsyncMock(return_value=FakeBleakClient()),
        ),
    ):
        updated = await client.async_read_current_data(
            FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring"),
            include_health=True,
        )

    assert updated.available is True
    assert updated.battery_level == 82
    assert updated.heart_rate is None
    assert updated.spo2 is None
    assert updated.stress is None


async def test_ble_client_skips_health_measurements_while_charging() -> None:
    class FakeBleakClient:
        def __init__(self) -> None:
            self.handler = None
            self.commands: list[bytes] = []

        async def start_notify(self, _uuid, handler) -> None:
            self.handler = handler

        async def write_gatt_char(self, _uuid, payload: bytes) -> None:
            self.commands.append(payload)
            assert self.handler is not None
            if payload[0] == 0x03:
                self.handler(1, bytearray(_battery_notification(charging=True)))
            elif payload[0] == 0x69:
                raise AssertionError("Health commands should be skipped while charging")

        async def stop_notify(self, _uuid) -> None:
            return None

        async def disconnect(self) -> None:
            return None

    fake_client = FakeBleakClient()
    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    client = FitorbBleClient(
        hass,
        "AA:BB:CC:DD:EE:FF",
        response_timeout=0.05,
    )

    with (
        patch(
            (
                "custom_components.fitorb.bluetooth.bluetooth"
                ".async_ble_device_from_address"
            ),
            return_value=object(),
        ),
        patch(
            "custom_components.fitorb.bluetooth.establish_connection",
            AsyncMock(return_value=fake_client),
        ),
    ):
        updated = await client.async_read_current_data(
            FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring"),
            include_health=True,
        )

    assert updated.available is True
    assert updated.is_charging is True
    assert not any(command[0] == 0x69 for command in fake_client.commands)


async def test_ble_client_keeps_activity_when_optional_health_write_fails(
    caplog,
) -> None:
    class FakeBleakClient:
        def __init__(self) -> None:
            self.handler = None

        async def start_notify(self, _uuid, handler) -> None:
            self.handler = handler

        async def write_gatt_char(self, _uuid, payload: bytes) -> None:
            if payload[0] == 0x03:
                assert self.handler is not None
                self.handler(1, bytearray(_battery_notification(level=82)))
            elif payload[0] == 0x43:
                assert self.handler is not None
                self.handler(
                    1,
                    bytearray(
                        _activity_notification(
                            steps=981,
                            calories=55,
                            distance=594,
                        )
                    ),
                )
            elif payload[0] == 0x69:
                raise RuntimeError("GATT Protocol Error: Unlikely Error")

        async def stop_notify(self, _uuid) -> None:
            raise RuntimeError("Service Discovery has not been performed yet")

        async def disconnect(self) -> None:
            return None

    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    client = FitorbBleClient(
        hass,
        "AA:BB:CC:DD:EE:FF",
        response_timeout=0.05,
    )
    caplog.set_level("DEBUG", logger="custom_components.fitorb.bluetooth")

    with (
        patch(
            (
                "custom_components.fitorb.bluetooth.bluetooth"
                ".async_ble_device_from_address"
            ),
            return_value=object(),
        ),
        patch(
            "custom_components.fitorb.bluetooth.establish_connection",
            AsyncMock(return_value=FakeBleakClient()),
        ),
    ):
        updated = await client.async_read_current_data(
            FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring"),
            include_health=True,
        )

    assert updated.available is True
    assert updated.battery_level == 82
    assert updated.steps == 981
    assert updated.calories == 55
    assert updated.distance == 594
    assert updated.heart_rate is None
    assert all(record.exc_info is None for record in caplog.records)


async def test_ble_client_skips_history_when_ble_session_is_lost() -> None:
    class FakeBleakClient:
        def __init__(self) -> None:
            self.handler = None
            self.commands: list[bytes] = []

        async def start_notify(self, _uuid, handler) -> None:
            self.handler = handler

        async def write_gatt_char(self, _uuid, payload: bytes) -> None:
            self.commands.append(payload)
            if payload[0] == 0x03:
                assert self.handler is not None
                self.handler(1, bytearray(_battery_notification(level=82)))
            elif payload[0] == 0x43:
                assert self.handler is not None
                self.handler(
                    1,
                    bytearray(
                        _activity_notification(
                            steps=981,
                            calories=55,
                            distance=594,
                        )
                    ),
                )
            elif payload[0] == 0x69:
                raise RuntimeError("Service Discovery has not been performed yet")

        async def stop_notify(self, _uuid) -> None:
            raise RuntimeError("Service Discovery has not been performed yet")

        async def disconnect(self) -> None:
            return None

    fake_client = FakeBleakClient()
    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    client = FitorbBleClient(
        hass,
        "AA:BB:CC:DD:EE:FF",
        response_timeout=0.05,
    )

    with (
        patch(
            (
                "custom_components.fitorb.bluetooth.bluetooth"
                ".async_ble_device_from_address"
            ),
            return_value=object(),
        ),
        patch(
            "custom_components.fitorb.bluetooth.establish_connection",
            AsyncMock(return_value=fake_client),
        ),
    ):
        result = await client.async_read_current_data_with_history(
            FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring"),
            include_health=True,
            history_request=FitorbHistoryRequest(
                days=(date(2026, 6, 26), date(2026, 6, 25)),
                day_offsets=(0, 1),
            ),
        )

    assert result.data.available is True
    assert result.data.battery_level == 82
    assert result.data.steps == 981
    assert result.history is None
    assert not any(command[0] == 0x15 for command in fake_client.commands)


async def test_ble_client_optional_timeout_logs_without_traceback(caplog) -> None:
    client = _test_client()
    queue: asyncio.Queue[bytes] = asyncio.Queue()
    snapshot = FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring")
    caplog.set_level("DEBUG", logger="custom_components.fitorb.bluetooth")

    updated = await client._drain_optional_response(
        queue,
        snapshot,
        expected_kind=NotificationKind.HEART_RATE,
    )

    assert updated is snapshot
    assert caplog.records[-1].message == (
        "No Fitorb heart_rate response; keeping other current values"
    )
    assert caplog.records[-1].exc_info is None


async def test_ble_client_health_optional_timeout_uses_short_timeout() -> None:
    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    client = FitorbBleClient(
        hass,
        "AA:BB:CC:DD:EE:FF",
        response_timeout=5,
        health_response_timeout=0.05,
    )
    queue: asyncio.Queue[bytes] = asyncio.Queue()
    snapshot = FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring")

    updated = await asyncio.wait_for(
        client._drain_optional_response(
            queue,
            snapshot,
            expected_kind=NotificationKind.HEART_RATE,
        ),
        timeout=0.5,
    )

    assert updated is snapshot


async def test_ble_client_health_running_state_extends_timeout() -> None:
    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    client = FitorbBleClient(
        hass,
        "AA:BB:CC:DD:EE:FF",
        response_timeout=5,
        health_response_timeout=0.05,
        health_measurement_timeout=0.5,
    )
    queue: asyncio.Queue[bytes] = asyncio.Queue()
    snapshot = FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring")

    async def _enqueue_measurement() -> None:
        await queue.put(_health_notification(0x01, running=True))
        await asyncio.sleep(0.12)
        await queue.put(_health_notification(0x01, running=False, value=72))

    task = asyncio.create_task(_enqueue_measurement())
    updated = await asyncio.wait_for(
        client._drain_optional_response(
            queue,
            snapshot,
            expected_kind=NotificationKind.HEART_RATE,
        ),
        timeout=1,
    )
    await task

    assert updated.heart_rate == 72


async def test_ble_client_health_no_value_response_extends_timeout(caplog) -> None:
    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    client = FitorbBleClient(
        hass,
        "AA:BB:CC:DD:EE:FF",
        response_timeout=5,
        health_response_timeout=0.05,
        health_measurement_timeout=0.5,
    )
    queue: asyncio.Queue[bytes] = asyncio.Queue()
    snapshot = FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring")
    caplog.set_level("DEBUG", logger="custom_components.fitorb.bluetooth")

    async def _enqueue_measurement() -> None:
        await queue.put(
            bytes([0x69, 0x01, 0x00, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0x6A])
        )
        await asyncio.sleep(0.12)
        await queue.put(_health_notification(0x01, running=False, value=72))

    task = asyncio.create_task(_enqueue_measurement())
    updated = await asyncio.wait_for(
        client._drain_optional_response(
            queue,
            snapshot,
            expected_kind=NotificationKind.HEART_RATE,
        ),
        timeout=1,
    )
    await task

    assert updated.heart_rate == 72
    assert (
        "Fitorb heart_rate response did not include a value yet: "
        "6901000000000000000000000000006a"
        in [record.message for record in caplog.records]
    )


async def test_ble_client_health_waits_for_final_result() -> None:
    client = _test_client()
    queue: asyncio.Queue[bytes] = asyncio.Queue()
    await queue.put(_health_notification(0x01, running=True))
    await queue.put(_health_notification(0x01, running=False, value=72))
    await queue.put(_battery_notification(level=33))
    snapshot = FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring")

    updated = await client._drain_until_expected(
        queue,
        snapshot,
        expected_kind=NotificationKind.HEART_RATE,
    )

    assert updated.heart_rate == 72
    assert queue.qsize() == 1


async def test_ble_client_raises_when_expected_response_times_out() -> None:
    client = _test_client()
    queue: asyncio.Queue[bytes] = asyncio.Queue()
    await queue.put(_unknown_notification())
    snapshot = FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring")

    with pytest.raises(
        FitorbResponseTimeout,
        match="Timed out waiting for Fitorb battery response",
    ):
        await client._drain_until_expected(
            queue,
            snapshot,
            expected_kind=NotificationKind.BATTERY,
        )


async def test_ble_client_reads_heart_rate_history_after_live_values() -> None:
    class FakeBleakClient:
        def __init__(self) -> None:
            self.handler = None
            self.commands: list[bytes] = []

        async def start_notify(self, _uuid, handler) -> None:
            self.handler = handler

        async def write_gatt_char(self, _uuid, payload: bytes) -> None:
            self.commands.append(payload)
            assert self.handler is not None
            if payload[0] == 0x03:
                self.handler(1, bytearray(_battery_notification(level=82)))
            elif payload[0] == 0x15:
                self.handler(
                    1,
                    bytearray(
                        bytes([21, 0, 2, 5, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 28])
                    ),
                )
                self.handler(
                    1,
                    bytearray(
                        bytes([21, 1, 0, 193, 61, 106, 72, 0, 0, 0, 0, 0, 75, 0, 0, 211])
                    ),
                )

        async def stop_notify(self, _uuid) -> None:
            return None

        async def disconnect(self) -> None:
            return None

    fake_client = FakeBleakClient()
    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    client = FitorbBleClient(hass, "AA:BB:CC:DD:EE:FF", response_timeout=0.05)

    with (
        patch(
            "custom_components.fitorb.bluetooth.bluetooth.async_ble_device_from_address",
            return_value=object(),
        ),
        patch(
            "custom_components.fitorb.bluetooth.establish_connection",
            AsyncMock(return_value=fake_client),
        ),
    ):
        result = await client.async_read_current_data_with_history(
            FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring"),
            include_health=False,
            history_request=FitorbHistoryRequest(
                days=(date(2026, 6, 26),),
                day_offsets=(0,),
            ),
        )

    assert isinstance(result, FitorbReadResult)
    assert result.data.battery_level == 82
    assert result.history is not None
    assert result.history.status == "success"
    assert [sample.value for sample in result.history.samples] == [72, 75]
    assert result.history.unknown_packets == 0
    assert result.history.malformed_packets == 0
    assert any(command[0] == 0x15 for command in fake_client.commands)


async def test_ble_client_reads_sleep_history_from_big_data() -> None:
    sleep_payload = bytes(
        [
            1,
            0,
            16,
            0x64,
            0x05,
            0x34,
            0x01,
            2,
            60,
            3,
            45,
            4,
            48,
            2,
            120,
            5,
            5,
            3,
            90,
        ]
    )
    sleep_frame = (
        bytes([0xBC, 0x27, len(sleep_payload), 0, 0x79, 0xED]) + sleep_payload
    )

    class FakeBleakClient:
        def __init__(self) -> None:
            self.handlers = {}
            self.commands: list[tuple[str, bytes]] = []

        async def start_notify(self, uuid, handler) -> None:
            self.handlers[uuid] = handler

        async def write_gatt_char(self, uuid, payload: bytes) -> None:
            self.commands.append((uuid, payload))
            if uuid == CMD_WRITE_CHAR_UUID and payload[0] == 0x03:
                self.handlers[CMD_NOTIFY_CHAR_UUID](
                    1, bytearray(_battery_notification(level=82))
                )
            elif uuid == CMD_WRITE_CHAR_UUID and payload[0] == 0x15:
                self.handlers[CMD_NOTIFY_CHAR_UUID](
                    1,
                    bytearray(
                        bytes([21, 0, 2, 5, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 28])
                    ),
                )
                self.handlers[CMD_NOTIFY_CHAR_UUID](
                    1,
                    bytearray(
                        bytes(
                            [
                                21,
                                1,
                                0,
                                193,
                                61,
                                106,
                                72,
                                0,
                                0,
                                0,
                                0,
                                0,
                                75,
                                0,
                                0,
                                211,
                            ]
                        )
                    ),
                )
            elif uuid == RAW_WRITE_CHAR_UUID and payload[:2] == bytes([0xBC, 0x27]):
                self.handlers[RAW_NOTIFY_CHAR_UUID](1, bytearray(sleep_frame))

        async def stop_notify(self, _uuid) -> None:
            return None

        async def disconnect(self) -> None:
            return None

    fake_client = FakeBleakClient()
    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    client = FitorbBleClient(hass, "AA:BB:CC:DD:EE:FF", response_timeout=0.05)

    with (
        patch(
            "custom_components.fitorb.bluetooth.bluetooth.async_ble_device_from_address",
            return_value=object(),
        ),
        patch(
            "custom_components.fitorb.bluetooth.establish_connection",
            AsyncMock(return_value=fake_client),
        ),
        patch(
            "custom_components.fitorb.bluetooth.date",
            Mock(today=Mock(return_value=date(2026, 6, 26))),
        ),
    ):
        result = await client.async_read_current_data_with_history(
            FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring"),
            include_health=False,
            history_request=FitorbHistoryRequest(
                days=(date(2026, 6, 26),),
                day_offsets=(0,),
            ),
        )

    assert result.data.battery_level == 82
    assert result.history is not None
    assert result.history.status == "success"
    assert result.history.sleep_summary == FitorbSleepSummary(
        source_day=date(2026, 6, 26),
        start=datetime(2026, 6, 26, 23, 0, tzinfo=UTC),
        end=datetime(2026, 6, 27, 5, 8, tzinfo=UTC),
        duration_minutes=368,
        asleep_minutes=363,
        awake_minutes=5,
        light_minutes=180,
        deep_minutes=135,
        rem_minutes=48,
    )
    sleep_stages = [
        sample.value
        for sample in result.history.samples
        if sample.metric is HistoryMetric.SLEEP_STAGE
    ]
    assert sleep_stages == [
        "light",
        "deep",
        "rem",
        "light",
        "awake",
        "deep",
    ]
    assert any(command[0] == RAW_WRITE_CHAR_UUID for command in fake_client.commands)


async def test_ble_client_history_timeout_keeps_live_result() -> None:
    class FakeBleakClient:
        def __init__(self) -> None:
            self.handler = None

        async def start_notify(self, _uuid, handler) -> None:
            self.handler = handler

        async def write_gatt_char(self, _uuid, payload: bytes) -> None:
            assert self.handler is not None
            if payload[0] == 0x03:
                self.handler(1, bytearray(_battery_notification(level=82)))
            elif payload[0] == 0x15:
                self.handler(
                    1,
                    bytearray(
                        bytes([21, 0, 3, 5, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 29])
                    ),
                )
                self.handler(
                    1,
                    bytearray(
                        bytes([21, 1, 0, 193, 61, 106, 72, 0, 0, 0, 0, 0, 75, 0, 0, 211])
                    ),
                )

        async def stop_notify(self, _uuid) -> None:
            return None

        async def disconnect(self) -> None:
            return None

    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    client = FitorbBleClient(hass, "AA:BB:CC:DD:EE:FF", response_timeout=0.05)

    with (
        patch(
            "custom_components.fitorb.bluetooth.bluetooth.async_ble_device_from_address",
            return_value=object(),
        ),
        patch(
            "custom_components.fitorb.bluetooth.establish_connection",
            AsyncMock(return_value=FakeBleakClient()),
        ),
    ):
        result = await client.async_read_current_data_with_history(
            FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring"),
            include_health=False,
            history_request=FitorbHistoryRequest(
                days=(date(2026, 6, 26),),
                day_offsets=(0,),
            ),
        )

    assert result.data.battery_level == 82
    assert result.history is not None
    assert result.history.status == "partial"
    assert [sample.value for sample in result.history.samples] == [72, 75]


async def test_ble_client_history_counts_unknown_and_malformed_packets() -> None:
    client = _test_client()
    queue: asyncio.Queue[bytes] = asyncio.Queue()
    await queue.put(_unknown_notification())
    await queue.put(_malformed_notification())
    await queue.put(bytes([21, 0, 2, 5, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 28]))
    await queue.put(bytes([21, 1, 0, 193, 61, 106, 72, 0, 0, 0, 0, 0, 75, 0, 0, 211]))

    packets, completed, unknown_packets, malformed_packets = (
        await client._drain_history_packets(
            queue,
            expected_command=0x15,
        )
    )

    assert completed is True
    assert unknown_packets == 1
    assert malformed_packets == 1
    assert len(packets) == 2


async def test_ble_client_history_timeout_reports_packet_counters() -> None:
    class FakeBleakClient:
        def __init__(self) -> None:
            self.handler = None

        async def start_notify(self, _uuid, handler) -> None:
            self.handler = handler

        async def write_gatt_char(self, _uuid, payload: bytes) -> None:
            assert self.handler is not None
            if payload[0] == 0x03:
                self.handler(1, bytearray(_battery_notification(level=82)))
            elif payload[0] == 0x15:
                self.handler(1, bytearray(_unknown_notification()))
                self.handler(1, bytearray(_malformed_notification()))

        async def stop_notify(self, _uuid) -> None:
            return None

        async def disconnect(self) -> None:
            return None

    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    client = FitorbBleClient(hass, "AA:BB:CC:DD:EE:FF", response_timeout=0.05)

    with (
        patch(
            (
                "custom_components.fitorb.bluetooth.bluetooth"
                ".async_ble_device_from_address"
            ),
            return_value=object(),
        ),
        patch(
            "custom_components.fitorb.bluetooth.establish_connection",
            AsyncMock(return_value=FakeBleakClient()),
        ),
    ):
        result = await client.async_read_current_data_with_history(
            FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring"),
            include_health=False,
            history_request=FitorbHistoryRequest(
                days=(date(2026, 6, 26),),
                day_offsets=(0,),
            ),
        )

    assert result.data.battery_level == 82
    assert result.history is not None
    assert result.history.status == "partial"
    assert result.history.samples == ()
    assert result.history.unknown_packets == 1
    assert result.history.malformed_packets == 1


async def test_ble_client_history_parse_failure_keeps_live_result() -> None:
    class FakeBleakClient:
        def __init__(self) -> None:
            self.handler = None

        async def start_notify(self, _uuid, handler) -> None:
            self.handler = handler

        async def write_gatt_char(self, _uuid, payload: bytes) -> None:
            assert self.handler is not None
            if payload[0] == 0x03:
                self.handler(1, bytearray(_battery_notification(level=82)))
            elif payload[0] == 0x15:
                self.handler(
                    1,
                    bytearray(
                        bytes([21, 0, 2, 5, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 28])
                    ),
                )
                self.handler(
                    1,
                    bytearray(
                        bytes([21, 1, 0, 193, 61, 106, 72, 0, 0, 0, 0, 0, 75, 0, 0, 211])
                    ),
                )

        async def stop_notify(self, _uuid) -> None:
            return None

        async def disconnect(self) -> None:
            return None

    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    client = FitorbBleClient(hass, "AA:BB:CC:DD:EE:FF", response_timeout=0.05)

    with (
        patch(
            "custom_components.fitorb.bluetooth.bluetooth.async_ble_device_from_address",
            return_value=object(),
        ),
        patch(
            "custom_components.fitorb.bluetooth.establish_connection",
            AsyncMock(return_value=FakeBleakClient()),
        ),
        patch(
            "custom_components.fitorb.bluetooth.parse_heart_rate_history_packets",
            side_effect=ValueError("bad history payload"),
        ),
    ):
        result = await client.async_read_current_data_with_history(
            FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring"),
            include_health=False,
            history_request=FitorbHistoryRequest(
                days=(date(2026, 6, 26),),
                day_offsets=(0,),
            ),
        )

    assert result.data.battery_level == 82
    assert result.history is not None
    assert result.history.status == "partial"
    assert result.history.samples == ()


async def test_setup_entry_keeps_entry_loaded_on_first_refresh_failure(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    entry.add_to_hass(hass)
    base_data = FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring")
    apply_history_summary = Mock(
        side_effect=lambda data: data.with_values(
            last_history_sample_count=42,
            last_history_status="success",
        )
    )
    fake_coordinator = SimpleNamespace(
        base_data=base_data,
        data=None,
        history_store=SimpleNamespace(async_load=AsyncMock()),
        _apply_history_store_summary=apply_history_summary,
        async_set_updated_data=AsyncMock(),
        async_config_entry_first_refresh=AsyncMock(
            side_effect=ConfigEntryNotReady("ring offline")
        ),
    )

    with (
        patch.object(fitorb_init, "FitorbBleClient", return_value=object()),
        patch.object(
            fitorb_init,
            "FitorbDataUpdateCoordinator",
            return_value=fake_coordinator,
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            AsyncMock(return_value=True),
        ) as forward_setups,
    ):
        result = await fitorb_init.async_setup_entry(hass, entry)

    assert result is True
    assert DOMAIN in hass.data
    assert hass.data[DOMAIN][entry.entry_id] is fake_coordinator
    fake_coordinator.async_set_updated_data.assert_called_once()
    fallback = fake_coordinator.async_set_updated_data.call_args.args[0]
    assert fallback.available is False
    assert fallback.last_error == "ring offline"
    assert fallback.last_history_sample_count == 42
    assert fallback.last_history_status == "success"
    apply_history_summary.assert_called_once_with(base_data)
    forward_setups.assert_awaited_once_with(entry, fitorb_init.PLATFORMS)


async def test_setup_entry_reloads_on_options_update(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    entry.add_to_hass(hass)
    base_data = FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring")
    fake_coordinator = SimpleNamespace(
        base_data=base_data,
        history_store=SimpleNamespace(async_load=AsyncMock()),
        async_set_updated_data=AsyncMock(),
        async_config_entry_first_refresh=AsyncMock(),
    )
    listeners = []
    unload_callbacks = []

    def _add_update_listener(listener):
        listeners.append(listener)
        return lambda: None

    def _async_on_unload(callback):
        unload_callbacks.append(callback)

    with (
        patch.object(entry, "add_update_listener", _add_update_listener),
        patch.object(entry, "async_on_unload", _async_on_unload),
        patch.object(fitorb_init, "FitorbBleClient", return_value=object()),
        patch.object(
            fitorb_init,
            "FitorbDataUpdateCoordinator",
            return_value=fake_coordinator,
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            AsyncMock(return_value=True),
        ),
        patch.object(
            hass.config_entries,
            "async_reload",
            AsyncMock(return_value=True),
        ) as async_reload,
    ):
        result = await fitorb_init.async_setup_entry(hass, entry)
        await listeners[0](hass, entry)

    assert result is True
    assert len(listeners) == 1
    assert len(unload_callbacks) == 1
    async_reload.assert_awaited_once_with(entry.entry_id)
