from __future__ import annotations

from homeassistant import config_entries
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.const import CONF_ADDRESS, CONF_NAME, CONF_SCAN_INTERVAL

from custom_components.fitorb.const import (
    CONF_HEALTH_POLL_INTERVAL,
    DOMAIN,
)


async def test_manual_flow_creates_entry(hass) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={CONF_ADDRESS: "AA:BB:CC:DD:EE:FF", CONF_NAME: "Ring"},
    )

    assert result["type"] is config_entries.FlowResultType.CREATE_ENTRY
    assert result["title"] == "Ring"
    assert result["data"] == {
        CONF_ADDRESS: "AA:BB:CC:DD:EE:FF",
        CONF_NAME: "Ring",
    }
    assert result["options"] == {
        CONF_SCAN_INTERVAL: 5,
        CONF_HEALTH_POLL_INTERVAL: 15,
    }


async def test_manual_flow_rejects_invalid_address(hass) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={CONF_ADDRESS: "not-a-mac", CONF_NAME: "Ring"},
    )

    assert result["type"] is config_entries.FlowResultType.FORM
    assert result["errors"] == {CONF_ADDRESS: "invalid_address"}


async def test_bluetooth_flow_creates_confirm_form(hass) -> None:
    service_info = BluetoothServiceInfoBleak(
        name="R06_ABCD",
        address="AA:BB:CC:DD:EE:FF",
        rssi=-55,
        manufacturer_data={},
        service_data={},
        service_uuids=[],
        source="local",
        device=None,
        advertisement=None,
        connectable=True,
        time=0.0,
        tx_power=None,
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_BLUETOOTH},
        data=service_info,
    )

    assert result["type"] is config_entries.FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"
