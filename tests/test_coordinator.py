from __future__ import annotations

from datetime import UTC

import pytest

from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fitorb.coordinator import FitorbDataUpdateCoordinator
from custom_components.fitorb.models import FitorbData


class FakeRingClient:
    def __init__(self, data: FitorbData | None = None, err: Exception | None = None) -> None:
        self.data = data
        self.err = err
        self.calls = 0

    async def async_read_current_data(self, base: FitorbData) -> FitorbData:
        self.calls += 1
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
