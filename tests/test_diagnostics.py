from __future__ import annotations

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
    assert diagnostics["unknown_notifications"] == 2
    assert diagnostics["malformed_notifications"] == 1
