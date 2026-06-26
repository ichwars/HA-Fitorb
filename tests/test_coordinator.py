from __future__ import annotations

import asyncio
from datetime import UTC
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.fitorb as fitorb_init
from custom_components.fitorb.bluetooth import FitorbBleClient
from custom_components.fitorb.const import DOMAIN
from custom_components.fitorb.coordinator import FitorbDataUpdateCoordinator
from custom_components.fitorb.models import FitorbData, NotificationKind


class FakeRingClient:
    def __init__(self, data: FitorbData | None = None, err: Exception | None = None) -> None:
        self.data = data
        self.err = err
        self.calls = 0
        self.include_health_calls: list[bool] = []

    async def async_read_current_data(
        self, base: FitorbData, *, include_health: bool = True
    ) -> FitorbData:
        self.calls += 1
        self.include_health_calls.append(include_health)
        if self.err is not None:
            raise self.err
        assert self.data is not None
        return self.data


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
    data = FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring", steps=123)
    client = FakeRingClient(data=data)
    coordinator = FitorbDataUpdateCoordinator(hass, entry, client)

    first = await coordinator._async_update_data()
    coordinator.async_set_updated_data(first)

    second = await coordinator._async_update_data()

    assert second.last_successful_update is not None
    assert client.include_health_calls == [True, False]


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
    payload[2] = 0x01 if not running else 0x00
    payload[3] = 0x00 if running else value
    return bytes(payload)


def _unknown_notification() -> bytes:
    payload = bytearray(16)
    payload[0] = 0xFF
    return bytes(payload)


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


async def test_setup_entry_propagates_first_refresh_failure(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    entry.add_to_hass(hass)
    fake_coordinator = SimpleNamespace(
        async_config_entry_first_refresh=AsyncMock(
            side_effect=ConfigEntryNotReady("ring offline")
        )
    )

    with (
        patch.object(fitorb_init, "FitorbBleClient", return_value=object()),
        patch.object(
            fitorb_init,
            "FitorbDataUpdateCoordinator",
            return_value=fake_coordinator,
        ),
        pytest.raises(ConfigEntryNotReady, match="ring offline"),
    ):
        await fitorb_init.async_setup_entry(hass, entry)

    assert DOMAIN in hass.data
    assert entry.entry_id not in hass.data[DOMAIN]
