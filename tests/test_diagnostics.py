from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fitorb.const import DOMAIN
from custom_components.fitorb.diagnostics import async_get_config_entry_diagnostics
from custom_components.fitorb.models import FitorbData


class FakeCoordinator:
    data = FitorbData(
        address="AA:BB:CC:DD:EE:FF",
        name="Ring",
        available=True,
        last_error="Failed to connect to AA:BB:CC:DD:EE:FF via 11:22:33:44:55:66",
        last_history_sync=datetime(2026, 6, 26, 3, 0, tzinfo=UTC),
        last_history_sample_count=24,
        last_history_status="success",
        last_history_first_sample=datetime(2026, 6, 25, 0, 0, tzinfo=UTC),
        last_history_last_sample=datetime(2026, 6, 26, 0, 0, tzinfo=UTC),
        sleep_start=datetime(2026, 6, 26, 23, 0, tzinfo=UTC),
        sleep_end=datetime(2026, 6, 27, 5, 8, tzinfo=UTC),
        sleep_duration_minutes=368,
        sleep_asleep_minutes=363,
        sleep_awake_minutes=5,
        sleep_light_minutes=180,
        sleep_deep_minutes=135,
        sleep_rem_minutes=48,
        history_unknown_packets=2,
        history_malformed_packets=1,
        unknown_notifications=2,
        malformed_notifications=1,
    )


async def test_diagnostics_redacts_address(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Ring",
        data={CONF_ADDRESS: "AA:BB:CC:DD:EE:FF", CONF_NAME: "Ring"},
        source="user",
        entry_id="entry-id",
        unique_id="AA:BB:CC:DD:EE:FF",
        options={},
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = FakeCoordinator()

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["address"] == "AA:BB:CC:***"
    assert diagnostics["available"] is True
    assert (
        diagnostics["last_error"]
        == "Failed to connect to AA:BB:CC:*** via 11:22:33:***"
    )
    assert diagnostics["unknown_notifications"] == 2
    assert diagnostics["malformed_notifications"] == 1
    assert diagnostics["history"] == {
        "last_sync": "2026-06-26T03:00:00+00:00",
        "sample_count": 24,
        "status": "success",
        "first_sample": "2026-06-25T00:00:00+00:00",
        "last_sample": "2026-06-26T00:00:00+00:00",
        "unknown_packets": 2,
        "malformed_packets": 1,
    }
    assert diagnostics["sleep"] == {
        "start": "2026-06-26T23:00:00+00:00",
        "end": "2026-06-27T05:08:00+00:00",
        "duration_minutes": 368,
        "asleep_minutes": 363,
        "awake_minutes": 5,
        "light_minutes": 180,
        "deep_minutes": 135,
        "rem_minutes": 48,
    }
