from __future__ import annotations

from homeassistant import config_entries
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.const import CONF_ADDRESS, CONF_NAME, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fitorb.const import (
    CONF_HEALTH_POLL_INTERVAL,
    DOMAIN,
)


def _service_info() -> BluetoothServiceInfoBleak:
    return BluetoothServiceInfoBleak(
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
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_BLUETOOTH},
        data=_service_info(),
    )

    assert result["type"] is config_entries.FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"
    assert result["description_placeholders"] == {"name": "R06_ABCD"}


async def test_bluetooth_confirm_creates_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_BLUETOOTH},
        data=_service_info(),
    )

    assert result["type"] is config_entries.FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={},
    )

    assert result["type"] is config_entries.FlowResultType.CREATE_ENTRY
    assert result["title"] == "R06_ABCD"
    assert result["data"] == {
        CONF_ADDRESS: "AA:BB:CC:DD:EE:FF",
        CONF_NAME: "R06_ABCD",
    }
    assert result["options"] == {
        CONF_SCAN_INTERVAL: 5,
        CONF_HEALTH_POLL_INTERVAL: 15,
    }


async def test_bluetooth_confirm_aborts_if_device_was_configured(
    hass: HomeAssistant,
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_BLUETOOTH},
        data=_service_info(),
    )

    assert result["type"] is config_entries.FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="AA:BB:CC:DD:EE:FF",
        data={
            CONF_ADDRESS: "AA:BB:CC:DD:EE:FF",
            CONF_NAME: "Existing Ring",
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={},
    )

    assert result["type"] is config_entries.FlowResultType.ABORT
    assert result["reason"] == "already_configured"
