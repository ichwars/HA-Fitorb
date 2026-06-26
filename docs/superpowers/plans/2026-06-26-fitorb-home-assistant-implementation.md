# Fitorb Home Assistant Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a HACS-installable Home Assistant custom integration named `fitorb` that exposes stable current Fitorb/Colmi-compatible smart ring values as Home Assistant sensors.

**Architecture:** Keep the BLE protocol parser pure and unit-tested, then wrap it with a Home Assistant coordinator that performs short active BLE polling sessions. Home Assistant entities read from the coordinator snapshot and stay resilient when the ring is out of range or connected elsewhere.

**Tech Stack:** Python 3.12, Home Assistant custom integration APIs, Home Assistant Bluetooth helpers, Bleak, pytest, pytest-homeassistant-custom-component, Ruff.

## Global Constraints

- Domain is `fitorb`.
- Version 1 focuses on stable current values only.
- Home Assistant has the official Bluetooth integration enabled.
- The USB Bluetooth adapter is passed through from Proxmox to the Home Assistant VM.
- Shelly Bluetooth proxies are not used because they cannot proxy active GATT connections.
- Historical heart rate, SpO2, stress, step details, sleep sync, and long-running raw recording are out of Version 1 scope.
- Default battery and day-summary polling interval is 5 minutes.
- Default heart rate, SpO2, and stress polling interval is 15 minutes.
- Connection timeout is 20 seconds.
- Individual command response timeout is 10 seconds.
- Raw PPG and accelerometer data are disabled by default and only logged or exposed diagnostically when explicitly enabled.
- Unknown notifications are debug logs only and must not fail an update.
- The integration must not crash Home Assistant when the ring is out of range, asleep, charging, or connected to the phone app.

---

## File Structure

Create these files:

- `custom_components/fitorb/__init__.py`: config-entry setup, runtime data creation, platform forwarding, unload.
- `custom_components/fitorb/binary_sensor.py`: charging and BLE reachability binary entities.
- `custom_components/fitorb/bluetooth.py`: BLE client wrapper and active read sequence.
- `custom_components/fitorb/config_flow.py`: UI setup through Bluetooth discovery or manual address entry.
- `custom_components/fitorb/const.py`: domain, defaults, UUIDs, config keys, platforms.
- `custom_components/fitorb/coordinator.py`: DataUpdateCoordinator that polls the ring and stores snapshots.
- `custom_components/fitorb/diagnostics.py`: redacted diagnostics.
- `custom_components/fitorb/manifest.json`: Home Assistant integration metadata.
- `custom_components/fitorb/models.py`: dataclasses and typed notification models.
- `custom_components/fitorb/protocol.py`: pure command builder and notification parser.
- `custom_components/fitorb/sensor.py`: numeric and timestamp sensor entities.
- `custom_components/fitorb/strings.json`: config flow strings.
- `custom_components/fitorb/translations/de.json`: German UI strings.
- `custom_components/fitorb/translations/en.json`: English UI strings.
- `hacs.json`: HACS metadata.
- `README.md`: installation, Proxmox Bluetooth passthrough notes, logging and known limits.
- `pyproject.toml`: test/lint configuration.
- `requirements-dev.txt`: local development dependencies.
- `tests/conftest.py`: Home Assistant custom-component test setup.
- `tests/test_config_flow.py`: config-flow tests.
- `tests/test_coordinator.py`: coordinator behavior tests with mocked BLE client.
- `tests/test_diagnostics.py`: diagnostics redaction tests.
- `tests/test_manifest.py`: packaging metadata tests.
- `tests/test_protocol.py`: protocol parser tests.
- `tests/test_sensor.py`: entity setup/value tests.

---

### Task 1: Repository And Integration Metadata

**Files:**
- Create: `pyproject.toml`
- Create: `requirements-dev.txt`
- Create: `hacs.json`
- Create: `custom_components/fitorb/manifest.json`
- Create: `custom_components/fitorb/const.py`
- Create: `custom_components/fitorb/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_manifest.py`

**Interfaces:**
- Produces: `DOMAIN: str`, `PLATFORMS: list[Platform]`, polling defaults, and manifest metadata used by every later task.
- Produces: empty config-entry setup that later tasks extend without changing function names.

- [ ] **Step 1: Write the failing metadata test**

Create `tests/test_manifest.py`:

```python
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_manifest_declares_bluetooth_dependency() -> None:
    manifest = json.loads(
        (ROOT / "custom_components" / "fitorb" / "manifest.json").read_text()
    )

    assert manifest["domain"] == "fitorb"
    assert manifest["name"] == "Fitorb Smart Ring"
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "local_polling"
    assert "bluetooth" in manifest["dependencies"]
    assert manifest["bluetooth"][0]["connectable"] is True


def test_hacs_metadata_points_to_integration() -> None:
    hacs = json.loads((ROOT / "hacs.json").read_text())

    assert hacs["name"] == "Fitorb Smart Ring"
    assert hacs["render_readme"] is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_manifest.py -v`

Expected: FAIL because `custom_components/fitorb/manifest.json` and `hacs.json` do not exist.

- [ ] **Step 3: Add metadata and base constants**

Create `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.ruff]
line-length = 88
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]
```

Create `requirements-dev.txt`:

```text
homeassistant>=2026.6.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
pytest-homeassistant-custom-component>=0.13.0
ruff>=0.5.0
```

Create `hacs.json`:

```json
{
  "name": "Fitorb Smart Ring",
  "render_readme": true,
  "domains": ["sensor", "binary_sensor"],
  "homeassistant": "2026.6.0"
}
```

Create `custom_components/fitorb/manifest.json`:

```json
{
  "domain": "fitorb",
  "name": "Fitorb Smart Ring",
  "after_dependencies": ["bluetooth"],
  "bluetooth": [
    {
      "local_name": "R0?_????",
      "connectable": true
    }
  ],
  "codeowners": [],
  "config_flow": true,
  "dependencies": ["bluetooth"],
  "documentation": "https://github.com/droth/ha-fitorb",
  "integration_type": "device",
  "iot_class": "local_polling",
  "issue_tracker": "https://github.com/droth/ha-fitorb/issues",
  "requirements": ["bleak-retry-connector>=3.8.0"],
  "version": "0.1.0"
}
```

Create `custom_components/fitorb/const.py`:

```python
from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "fitorb"
DEFAULT_NAME = "Fitorb Smart Ring"

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

CONF_HEALTH_POLL_INTERVAL = "health_poll_interval"

DEFAULT_SUMMARY_POLL_INTERVAL = timedelta(minutes=5)
DEFAULT_HEALTH_POLL_INTERVAL = timedelta(minutes=15)
DEFAULT_CONNECT_TIMEOUT = 20.0
DEFAULT_RESPONSE_TIMEOUT = 10.0

CMD_SERVICE_UUID = "6e40fff0-b5a3-f393-e0a9-e50e24dcca9e"
CMD_WRITE_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
CMD_NOTIFY_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
RAW_SERVICE_UUID = "de5bf728-d711-4e47-af26-65e3012a5dc7"
RAW_WRITE_CHAR_UUID = "de5bf72a-d711-4e47-af26-65e3012a5dc7"
RAW_NOTIFY_CHAR_UUID = "de5bf729-d711-4e47-af26-65e3012a5dc7"
```

Create `custom_components/fitorb/__init__.py`:

```python
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Fitorb from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = None
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Fitorb config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
```

Create `tests/conftest.py`:

```python
from __future__ import annotations

pytest_plugins = "pytest_homeassistant_custom_component"
```

- [ ] **Step 4: Run the metadata test**

Run: `pytest tests/test_manifest.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml requirements-dev.txt hacs.json custom_components/fitorb tests
git commit -m "chore: scaffold fitorb integration metadata"
```

---

### Task 2: Protocol Models, Commands, And Parsers

**Files:**
- Create: `custom_components/fitorb/models.py`
- Create: `custom_components/fitorb/protocol.py`
- Create: `tests/test_protocol.py`

**Interfaces:**
- Consumes: UUID constants from `custom_components/fitorb/const.py`.
- Produces: `build_command(hex_payload: str) -> bytes`.
- Produces: `parse_notification(data: bytes) -> ParsedNotification | None`.
- Produces: `FitorbData`, `ParsedNotification`, `NotificationKind`.

- [ ] **Step 1: Write failing protocol tests**

Create `tests/test_protocol.py`:

```python
from __future__ import annotations

from custom_components.fitorb.models import NotificationKind
from custom_components.fitorb.protocol import build_command, parse_notification


def test_build_command_pads_to_16_bytes_and_adds_checksum() -> None:
    command = build_command("0a0200")

    assert command == bytes(
        [0x0A, 0x02, 0x00, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0x0C]
    )


def test_build_command_rejects_odd_hex() -> None:
    try:
        build_command("abc")
    except ValueError as err:
        assert "even number" in str(err)
    else:
        raise AssertionError("Expected ValueError")


def test_parse_direct_battery_response() -> None:
    parsed = parse_notification(bytes([0x03, 71, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 75]))

    assert parsed is not None
    assert parsed.kind is NotificationKind.BATTERY
    assert parsed.values == {"battery_level": 71, "is_charging": True}


def test_parse_activity_summary() -> None:
    parsed = parse_notification(
        bytes([0x73, 0x12, 0, 11, 239, 2, 34, 9, 0, 7, 207, 0, 0, 0, 0, 130])
    )

    assert parsed is not None
    assert parsed.kind is NotificationKind.ACTIVITY
    assert parsed.values == {"steps": 3055, "calories": 139, "distance": 1999}


def test_parse_heart_rate_result() -> None:
    parsed = parse_notification(bytes([0x69, 0x01, 0x01, 64, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 207]))

    assert parsed is not None
    assert parsed.kind is NotificationKind.HEART_RATE
    assert parsed.values == {"heart_rate": 64, "running": False}


def test_parse_spo2_result() -> None:
    parsed = parse_notification(bytes([0x69, 0x03, 0x01, 98, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 5]))

    assert parsed is not None
    assert parsed.kind is NotificationKind.SPO2
    assert parsed.values == {"spo2": 98, "running": False}


def test_parse_stress_result() -> None:
    parsed = parse_notification(bytes([0x69, 0x08, 0x01, 32, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 164]))

    assert parsed is not None
    assert parsed.kind is NotificationKind.STRESS
    assert parsed.values == {"stress": 32, "running": False}


def test_parse_unknown_notification_returns_none() -> None:
    assert parse_notification(bytes([0x99, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_protocol.py -v`

Expected: FAIL because `models.py` and `protocol.py` do not exist.

- [ ] **Step 3: Add models and protocol parser**

Create `custom_components/fitorb/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any


class NotificationKind(StrEnum):
    """Known ring notification classes."""

    BATTERY = "battery"
    ACTIVITY = "activity"
    HEART_RATE = "heart_rate"
    SPO2 = "spo2"
    STRESS = "stress"
    RAW_SPO2 = "raw_spo2"
    RAW_PPG = "raw_ppg"
    RAW_ACCELEROMETER = "raw_accelerometer"


@dataclass(frozen=True, slots=True)
class ParsedNotification:
    """Parsed BLE notification payload."""

    kind: NotificationKind
    values: dict[str, Any]
    raw_hex: str


@dataclass(frozen=True, slots=True)
class FitorbData:
    """Latest known ring data snapshot."""

    address: str
    name: str
    available: bool = False
    battery_level: int | None = None
    is_charging: bool | None = None
    steps: int | None = None
    calories: int | None = None
    distance: int | None = None
    heart_rate: int | None = None
    spo2: int | None = None
    stress: int | None = None
    last_successful_update: datetime | None = None
    last_error: str | None = None
    unknown_notifications: int = 0
    malformed_notifications: int = 0

    def with_values(self, **values: Any) -> FitorbData:
        """Return a copy with updated values."""
        return replace(self, **values)
```

Create `custom_components/fitorb/protocol.py`:

```python
from __future__ import annotations

from .models import NotificationKind, ParsedNotification

COMMAND_BATTERY = "03"
COMMAND_SET_METRIC_UNITS = "0a0200"
COMMAND_ACTIVITY = "43"
COMMAND_HEART_RATE = "6901"
COMMAND_SPO2 = "6903"
COMMAND_STRESS = "6908"
COMMAND_KEEPALIVE = "39"


def build_command(hex_payload: str) -> bytes:
    """Build a padded 16-byte Colmi command with checksum."""
    if len(hex_payload) % 2:
        raise ValueError("hex payload must have an even number of characters")
    if len(hex_payload) > 30:
        raise ValueError("hex payload must be at most 30 characters")

    try:
        payload = bytes.fromhex(hex_payload)
    except ValueError as err:
        raise ValueError("hex payload contains non-hex characters") from err

    command = bytearray(16)
    command[: len(payload)] = payload
    command[15] = sum(command[:15]) & 0xFF
    return bytes(command)


def _ensure_16(data: bytes) -> bool:
    return len(data) == 16


def _parse_health_result(
    data: bytes,
    kind: NotificationKind,
    value_key: str,
) -> ParsedNotification | None:
    if not _ensure_16(data) or data[0] != 0x69:
        return None

    running = data[3] == 0
    values: dict[str, int | bool | None] = {"running": running}
    if not running and data[2] == 0x01:
        values[value_key] = data[3]
    else:
        values[value_key] = None
    return ParsedNotification(kind=kind, values=values, raw_hex=data.hex())


def parse_notification(data: bytes | bytearray) -> ParsedNotification | None:
    """Parse a 16-byte Colmi notification."""
    payload = bytes(data)
    if not _ensure_16(payload):
        return None

    if payload[0] == 0x03:
        return ParsedNotification(
            kind=NotificationKind.BATTERY,
            values={"battery_level": payload[1], "is_charging": payload[2] == 1},
            raw_hex=payload.hex(),
        )

    if payload[0] == 0x73 and payload[1] == 0x0C:
        return ParsedNotification(
            kind=NotificationKind.BATTERY,
            values={"battery_level": payload[2], "is_charging": payload[3] == 1},
            raw_hex=payload.hex(),
        )

    if payload[0] == 0x73 and payload[1] == 0x12:
        steps = (payload[2] << 16) | (payload[3] << 8) | payload[4]
        calories = ((payload[5] << 16) | (payload[6] << 8) | payload[7]) // 1000
        distance = (payload[8] << 16) | (payload[9] << 8) | payload[10]
        return ParsedNotification(
            kind=NotificationKind.ACTIVITY,
            values={"steps": steps, "calories": calories, "distance": distance},
            raw_hex=payload.hex(),
        )

    if payload[0] == 0x69 and payload[1] == 0x01:
        return _parse_health_result(payload, NotificationKind.HEART_RATE, "heart_rate")

    if payload[0] == 0x69 and payload[1] == 0x03:
        return _parse_health_result(payload, NotificationKind.SPO2, "spo2")

    if payload[0] == 0x69 and payload[1] == 0x08:
        return _parse_health_result(payload, NotificationKind.STRESS, "stress")

    return None
```

- [ ] **Step 4: Run protocol tests**

Run: `pytest tests/test_protocol.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/fitorb/models.py custom_components/fitorb/protocol.py tests/test_protocol.py
git commit -m "feat: add fitorb protocol parser"
```

---

### Task 3: Config Flow And Translations

**Files:**
- Create: `custom_components/fitorb/config_flow.py`
- Create: `custom_components/fitorb/strings.json`
- Create: `custom_components/fitorb/translations/en.json`
- Create: `custom_components/fitorb/translations/de.json`
- Create: `tests/test_config_flow.py`

**Interfaces:**
- Consumes: `DOMAIN`, `DEFAULT_NAME`, and polling defaults from `const.py`.
- Produces: config entries with `data={CONF_ADDRESS: str, CONF_NAME: str}` and `options={CONF_SCAN_INTERVAL: int, CONF_HEALTH_POLL_INTERVAL: int}`.

- [ ] **Step 1: Write failing config-flow tests**

Create `tests/test_config_flow.py`:

```python
from __future__ import annotations

from homeassistant import config_entries
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.const import CONF_ADDRESS, CONF_NAME

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
    assert result["options"][CONF_HEALTH_POLL_INTERVAL] == 15


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
```

- [ ] **Step 2: Run config-flow tests to verify they fail**

Run: `pytest tests/test_config_flow.py -v`

Expected: FAIL because `config_flow.py` does not exist.

- [ ] **Step 3: Add config flow implementation and strings**

Create `custom_components/fitorb/config_flow.py`:

```python
from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.const import CONF_ADDRESS, CONF_NAME, CONF_SCAN_INTERVAL
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_HEALTH_POLL_INTERVAL,
    DEFAULT_HEALTH_POLL_INTERVAL,
    DEFAULT_NAME,
    DEFAULT_SUMMARY_POLL_INTERVAL,
    DOMAIN,
)

_MAC_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$", re.IGNORECASE)


def _normalize_address(address: str) -> str:
    return address.strip().upper()


def _is_valid_address(address: str) -> bool:
    return bool(_MAC_RE.match(_normalize_address(address)))


class FitorbConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a Fitorb config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle manual setup."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = _normalize_address(user_input[CONF_ADDRESS])
            if not _is_valid_address(address):
                errors[CONF_ADDRESS] = "invalid_address"
            else:
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                name = user_input.get(CONF_NAME) or DEFAULT_NAME
                return self.async_create_entry(
                    title=name,
                    data={CONF_ADDRESS: address, CONF_NAME: name},
                    options={
                        CONF_SCAN_INTERVAL: int(DEFAULT_SUMMARY_POLL_INTERVAL.total_seconds() / 60),
                        CONF_HEALTH_POLL_INTERVAL: int(DEFAULT_HEALTH_POLL_INTERVAL.total_seconds() / 60),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): str,
                    vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                }
            ),
            errors=errors,
        )

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak) -> FlowResult:
        """Handle Bluetooth discovery."""
        address = _normalize_address(discovery_info.address)
        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()
        self._discovery = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info.name or DEFAULT_NAME}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Confirm Bluetooth discovery."""
        if self._discovery is None:
            return self.async_abort(reason="no_discovery_info")

        address = _normalize_address(self._discovery.address)
        name = self._discovery.name or DEFAULT_NAME
        if user_input is not None:
            return self.async_create_entry(
                title=name,
                data={CONF_ADDRESS: address, CONF_NAME: name},
                options={
                    CONF_SCAN_INTERVAL: int(DEFAULT_SUMMARY_POLL_INTERVAL.total_seconds() / 60),
                    CONF_HEALTH_POLL_INTERVAL: int(DEFAULT_HEALTH_POLL_INTERVAL.total_seconds() / 60),
                },
            )

        return self.async_show_form(step_id="bluetooth_confirm")
```

Create `custom_components/fitorb/strings.json`:

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Set up Fitorb Smart Ring",
        "description": "Enter the Bluetooth address of the ring.",
        "data": {
          "address": "Bluetooth address",
          "name": "Name"
        }
      },
      "bluetooth_confirm": {
        "title": "Set up {name}",
        "description": "Add this Fitorb/Colmi-compatible smart ring to Home Assistant?"
      }
    },
    "error": {
      "invalid_address": "Enter a Bluetooth MAC address such as AA:BB:CC:DD:EE:FF."
    },
    "abort": {
      "already_configured": "This ring is already configured.",
      "no_discovery_info": "Bluetooth discovery information is no longer available."
    }
  }
}
```

Create `custom_components/fitorb/translations/en.json` with the same content as `strings.json`.

Create `custom_components/fitorb/translations/de.json`:

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Fitorb Smart Ring einrichten",
        "description": "Gib die Bluetooth-Adresse des Rings ein.",
        "data": {
          "address": "Bluetooth-Adresse",
          "name": "Name"
        }
      },
      "bluetooth_confirm": {
        "title": "{name} einrichten",
        "description": "Diesen Fitorb-/Colmi-kompatiblen Smart Ring zu Home Assistant hinzufügen?"
      }
    },
    "error": {
      "invalid_address": "Gib eine Bluetooth-MAC-Adresse wie AA:BB:CC:DD:EE:FF ein."
    },
    "abort": {
      "already_configured": "Dieser Ring ist bereits eingerichtet.",
      "no_discovery_info": "Die Bluetooth-Erkennungsdaten sind nicht mehr verfügbar."
    }
  }
}
```

- [ ] **Step 4: Run config-flow tests**

Run: `pytest tests/test_config_flow.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/fitorb/config_flow.py custom_components/fitorb/strings.json custom_components/fitorb/translations tests/test_config_flow.py
git commit -m "feat: add fitorb config flow"
```

---

### Task 4: BLE Client And Coordinator

**Files:**
- Create: `custom_components/fitorb/bluetooth.py`
- Create: `custom_components/fitorb/coordinator.py`
- Modify: `custom_components/fitorb/__init__.py`
- Create: `tests/test_coordinator.py`

**Interfaces:**
- Consumes: `build_command`, `parse_notification`, `FitorbData`, config entry data.
- Produces: `FitorbBleClient.async_read_current_data(base: FitorbData) -> FitorbData`.
- Produces: `FitorbDataUpdateCoordinator.async_config_entry_first_refresh()`.
- Stores coordinator at `hass.data[DOMAIN][entry.entry_id]`.

- [ ] **Step 1: Write failing coordinator tests**

Create `tests/test_coordinator.py`:

```python
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


async def test_coordinator_updates_snapshot(hass: HomeAssistant, entry: MockConfigEntry) -> None:
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


async def test_coordinator_wraps_ble_errors(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    client = FakeRingClient(err=TimeoutError("ring timeout"))
    coordinator = FitorbDataUpdateCoordinator(hass, entry, client)

    with pytest.raises(UpdateFailed, match="ring timeout"):
        await coordinator._async_update_data()
```

- [ ] **Step 2: Run coordinator tests to verify they fail**

Run: `pytest tests/test_coordinator.py -v`

Expected: FAIL because `coordinator.py` and `bluetooth.py` do not exist.

- [ ] **Step 3: Add BLE client wrapper**

Create `custom_components/fitorb/bluetooth.py`:

```python
from __future__ import annotations

import asyncio
import logging

from bleak import BleakClient
from bleak_retry_connector import establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .const import (
    CMD_NOTIFY_CHAR_UUID,
    CMD_WRITE_CHAR_UUID,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_RESPONSE_TIMEOUT,
)
from .models import FitorbData, NotificationKind
from .protocol import (
    COMMAND_ACTIVITY,
    COMMAND_BATTERY,
    COMMAND_HEART_RATE,
    COMMAND_SET_METRIC_UNITS,
    COMMAND_SPO2,
    COMMAND_STRESS,
    build_command,
    parse_notification,
)

_LOGGER = logging.getLogger(__name__)


class FitorbBluetoothError(Exception):
    """Base exception for Fitorb Bluetooth failures."""


class FitorbDeviceUnavailable(FitorbBluetoothError):
    """Raised when no connectable BLE device is available."""


class FitorbBleClient:
    """Read current data from a Fitorb/Colmi-compatible ring."""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        *,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        response_timeout: float = DEFAULT_RESPONSE_TIMEOUT,
    ) -> None:
        self.hass = hass
        self.address = address
        self.connect_timeout = connect_timeout
        self.response_timeout = response_timeout

    async def async_read_current_data(self, base: FitorbData) -> FitorbData:
        """Connect to the ring and read the Version 1 current values."""
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass,
            self.address,
            connectable=True,
        )
        if ble_device is None:
            raise FitorbDeviceUnavailable("No connectable Bluetooth path to ring")

        queue: asyncio.Queue[bytes] = asyncio.Queue()

        def _notification_handler(_sender: int, data: bytearray) -> None:
            queue.put_nowait(bytes(data))

        client = await establish_connection(
            BleakClient,
            ble_device,
            self.address,
            timeout=self.connect_timeout,
        )
        try:
            await client.start_notify(CMD_NOTIFY_CHAR_UUID, _notification_handler)
            snapshot = base.with_values(available=True, last_error=None)
            for command in (
                COMMAND_BATTERY,
                COMMAND_SET_METRIC_UNITS,
                COMMAND_ACTIVITY,
                COMMAND_HEART_RATE,
                COMMAND_SPO2,
                COMMAND_STRESS,
            ):
                await client.write_gatt_char(CMD_WRITE_CHAR_UUID, build_command(command))
                snapshot = await self._drain_notifications(queue, snapshot)
            return snapshot
        finally:
            try:
                await client.stop_notify(CMD_NOTIFY_CHAR_UUID)
            except Exception:
                _LOGGER.debug("Unable to stop Fitorb notifications", exc_info=True)
            await client.disconnect()

    async def _drain_notifications(
        self,
        queue: asyncio.Queue[bytes],
        snapshot: FitorbData,
    ) -> FitorbData:
        """Drain currently available notifications after a command."""
        saw_response = False
        end_time = self.hass.loop.time() + self.response_timeout
        while self.hass.loop.time() < end_time:
            timeout = max(0.1, end_time - self.hass.loop.time())
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=timeout)
            except TimeoutError:
                break
            parsed = parse_notification(payload)
            if parsed is None:
                _LOGGER.debug("Unknown Fitorb notification: %s", payload.hex())
                snapshot = snapshot.with_values(
                    unknown_notifications=snapshot.unknown_notifications + 1
                )
                continue
            saw_response = True
            snapshot = _apply_notification(snapshot, parsed.kind, parsed.values)
            if parsed.values.get("running") is False:
                break
        if not saw_response:
            _LOGGER.debug("No Fitorb response before command timeout")
        return snapshot


def _apply_notification(
    snapshot: FitorbData,
    kind: NotificationKind,
    values: dict[str, object],
) -> FitorbData:
    """Apply a parsed notification to the data snapshot."""
    if kind is NotificationKind.BATTERY:
        return snapshot.with_values(
            battery_level=values["battery_level"],
            is_charging=values["is_charging"],
        )
    if kind is NotificationKind.ACTIVITY:
        return snapshot.with_values(
            steps=values["steps"],
            calories=values["calories"],
            distance=values["distance"],
        )
    if kind is NotificationKind.HEART_RATE and values.get("heart_rate") is not None:
        return snapshot.with_values(heart_rate=values["heart_rate"])
    if kind is NotificationKind.SPO2 and values.get("spo2") is not None:
        return snapshot.with_values(spo2=values["spo2"])
    if kind is NotificationKind.STRESS and values.get("stress") is not None:
        return snapshot.with_values(stress=values["stress"])
    return snapshot
```

- [ ] **Step 4: Add coordinator and wire setup**

Create `custom_components/fitorb/coordinator.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
import logging

from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .bluetooth import FitorbBleClient
from .const import DEFAULT_SUMMARY_POLL_INTERVAL, DOMAIN
from .models import FitorbData

_LOGGER = logging.getLogger(__name__)


class FitorbDataUpdateCoordinator(DataUpdateCoordinator[FitorbData]):
    """Coordinate polling a Fitorb smart ring."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: FitorbBleClient,
    ) -> None:
        self.entry = entry
        self.client = client
        self.base_data = FitorbData(
            address=entry.data[CONF_ADDRESS],
            name=entry.data.get(CONF_NAME, entry.title),
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SUMMARY_POLL_INTERVAL,
        )

    async def _async_update_data(self) -> FitorbData:
        """Fetch data from the ring."""
        try:
            base = self.data or self.base_data
            data = await self.client.async_read_current_data(base)
        except Exception as err:
            previous = self.data or self.base_data
            self.async_set_updated_data(
                previous.with_values(available=False, last_error=str(err))
            )
            raise UpdateFailed(str(err)) from err
        return data.with_values(
            available=True,
            last_error=None,
            last_successful_update=datetime.now(UTC),
        )
```

Modify `custom_components/fitorb/__init__.py`:

```python
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant

from .bluetooth import FitorbBleClient
from .const import DOMAIN, PLATFORMS
from .coordinator import FitorbDataUpdateCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Fitorb from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    client = FitorbBleClient(hass, entry.data[CONF_ADDRESS])
    coordinator = FitorbDataUpdateCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Fitorb config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
```

- [ ] **Step 5: Run coordinator tests**

Run: `pytest tests/test_coordinator.py -v`

Expected: PASS.

- [ ] **Step 6: Run protocol tests again**

Run: `pytest tests/test_protocol.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add custom_components/fitorb/__init__.py custom_components/fitorb/bluetooth.py custom_components/fitorb/coordinator.py tests/test_coordinator.py
git commit -m "feat: add fitorb bluetooth coordinator"
```

---

### Task 5: Sensor And Binary Sensor Entities

**Files:**
- Create: `custom_components/fitorb/sensor.py`
- Create: `custom_components/fitorb/binary_sensor.py`
- Create: `tests/test_sensor.py`

**Interfaces:**
- Consumes: coordinator stored at `hass.data[DOMAIN][entry.entry_id]`.
- Produces: sensors for battery, steps, calories, distance, heart rate, SpO2, stress, last successful update.
- Produces: binary sensors for charging and connection state.

- [ ] **Step 1: Write failing entity tests**

Create `tests/test_sensor.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
import logging

from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from custom_components.fitorb.const import DOMAIN
from custom_components.fitorb.models import FitorbData
from custom_components.fitorb.sensor import FitorbSensorEntity
from custom_components.fitorb.binary_sensor import FitorbBinarySensorEntity


class FakeCoordinator(DataUpdateCoordinator[FitorbData]):
    def __init__(self, hass: HomeAssistant, data: FitorbData) -> None:
        self.base_data = data
        super().__init__(hass, logging.getLogger(__name__), name=DOMAIN)
        self.async_set_updated_data(data)


def test_battery_sensor_value(hass: HomeAssistant) -> None:
    data = FitorbData(
        address="AA:BB:CC:DD:EE:FF",
        name="Ring",
        available=True,
        battery_level=72,
    )
    coordinator = FakeCoordinator(hass, data)
    entity = FitorbSensorEntity(coordinator, "battery_level")

    assert entity.unique_id == "aabbccddeeff_battery_level"
    assert entity.native_value == 72
    assert entity.native_unit_of_measurement == PERCENTAGE
    assert entity.available is True


def test_last_update_sensor_value(hass: HomeAssistant) -> None:
    stamp = datetime(2026, 6, 26, 1, 2, 3, tzinfo=UTC)
    data = FitorbData(
        address="AA:BB:CC:DD:EE:FF",
        name="Ring",
        available=True,
        last_successful_update=stamp,
    )
    coordinator = FakeCoordinator(hass, data)
    entity = FitorbSensorEntity(coordinator, "last_successful_update")

    assert entity.native_value == stamp


def test_charging_binary_sensor_value(hass: HomeAssistant) -> None:
    data = FitorbData(
        address="AA:BB:CC:DD:EE:FF",
        name="Ring",
        available=True,
        is_charging=True,
    )
    coordinator = FakeCoordinator(hass, data)
    entity = FitorbBinarySensorEntity(coordinator, "is_charging")

    assert entity.unique_id == "aabbccddeeff_is_charging"
    assert entity.is_on is True
```

- [ ] **Step 2: Run entity tests to verify they fail**

Run: `pytest tests/test_sensor.py -v`

Expected: FAIL because `sensor.py` and `binary_sensor.py` do not exist.

- [ ] **Step 3: Add numeric and timestamp sensors**

Create `custom_components/fitorb/sensor.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    UnitOfLength,
    PERCENTAGE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.typing import StateType

from .const import DOMAIN
from .coordinator import FitorbDataUpdateCoordinator
from .models import FitorbData


@dataclass(frozen=True, kw_only=True)
class FitorbSensorDescription(SensorEntityDescription):
    """Describe a Fitorb sensor."""

    value_fn: Callable[[FitorbData], StateType]


SENSOR_DESCRIPTIONS: dict[str, FitorbSensorDescription] = {
    "battery_level": FitorbSensorDescription(
        key="battery_level",
        translation_key="battery_level",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.battery_level,
    ),
    "steps": FitorbSensorDescription(
        key="steps",
        translation_key="steps",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.steps,
    ),
    "calories": FitorbSensorDescription(
        key="calories",
        translation_key="calories",
        native_unit_of_measurement="kcal",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.calories,
    ),
    "distance": FitorbSensorDescription(
        key="distance",
        translation_key="distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.distance,
    ),
    "heart_rate": FitorbSensorDescription(
        key="heart_rate",
        translation_key="heart_rate",
        native_unit_of_measurement="bpm",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.heart_rate,
    ),
    "spo2": FitorbSensorDescription(
        key="spo2",
        translation_key="spo2",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.spo2,
    ),
    "stress": FitorbSensorDescription(
        key="stress",
        translation_key="stress",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.stress,
    ),
    "last_successful_update": FitorbSensorDescription(
        key="last_successful_update",
        translation_key="last_successful_update",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.last_successful_update,
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Fitorb sensors."""
    coordinator: FitorbDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        FitorbSensorEntity(coordinator, key) for key in SENSOR_DESCRIPTIONS
    )


class FitorbSensorEntity(CoordinatorEntity[FitorbDataUpdateCoordinator], SensorEntity):
    """Represent a Fitorb sensor."""

    entity_description: FitorbSensorDescription

    def __init__(self, coordinator: FitorbDataUpdateCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self.entity_description = SENSOR_DESCRIPTIONS[key]
        address = coordinator.base_data.address.replace(":", "").lower()
        self._attr_unique_id = f"{address}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, address)},
            "name": coordinator.base_data.name,
            "manufacturer": "Fitorb",
            "model": "Colmi-compatible Smart Ring",
        }

    @property
    def available(self) -> bool:
        """Return entity availability."""
        data = self.coordinator.data
        return bool(data and data.available)

    @property
    def native_value(self) -> StateType:
        """Return the sensor value."""
        data = self.coordinator.data
        if data is None:
            return None
        return self.entity_description.value_fn(data)
```

- [ ] **Step 4: Add binary sensors**

Create `custom_components/fitorb/binary_sensor.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FitorbDataUpdateCoordinator
from .models import FitorbData


@dataclass(frozen=True, kw_only=True)
class FitorbBinarySensorDescription(BinarySensorEntityDescription):
    """Describe a Fitorb binary sensor."""

    value_fn: Callable[[FitorbData], bool | None]


BINARY_SENSOR_DESCRIPTIONS: dict[str, FitorbBinarySensorDescription] = {
    "is_charging": FitorbBinarySensorDescription(
        key="is_charging",
        translation_key="is_charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.is_charging,
    ),
    "connection_state": FitorbBinarySensorDescription(
        key="connection_state",
        translation_key="connection_state",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.available,
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Fitorb binary sensors."""
    coordinator: FitorbDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        FitorbBinarySensorEntity(coordinator, key) for key in BINARY_SENSOR_DESCRIPTIONS
    )


class FitorbBinarySensorEntity(
    CoordinatorEntity[FitorbDataUpdateCoordinator],
    BinarySensorEntity,
):
    """Represent a Fitorb binary sensor."""

    entity_description: FitorbBinarySensorDescription

    def __init__(self, coordinator: FitorbDataUpdateCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self.entity_description = BINARY_SENSOR_DESCRIPTIONS[key]
        address = coordinator.base_data.address.replace(":", "").lower()
        self._attr_unique_id = f"{address}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, address)},
            "name": coordinator.base_data.name,
            "manufacturer": "Fitorb",
            "model": "Colmi-compatible Smart Ring",
        }

    @property
    def available(self) -> bool:
        """Return entity availability."""
        data = self.coordinator.data
        if self.entity_description.key == "connection_state":
            return data is not None
        return bool(data and data.available)

    @property
    def is_on(self) -> bool | None:
        """Return the binary sensor state."""
        data = self.coordinator.data
        if data is None:
            return None
        return self.entity_description.value_fn(data)
```

- [ ] **Step 5: Run entity tests**

Run: `pytest tests/test_sensor.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add custom_components/fitorb/sensor.py custom_components/fitorb/binary_sensor.py tests/test_sensor.py
git commit -m "feat: add fitorb sensor entities"
```

---

### Task 6: Diagnostics, README, And Full Verification

**Files:**
- Create: `custom_components/fitorb/diagnostics.py`
- Create: `tests/test_diagnostics.py`
- Modify: `README.md`
- Modify: `custom_components/fitorb/strings.json`
- Modify: `custom_components/fitorb/translations/en.json`
- Modify: `custom_components/fitorb/translations/de.json`

**Interfaces:**
- Consumes: coordinator data stored under `hass.data[DOMAIN][entry.entry_id]`.
- Produces: `async_get_config_entry_diagnostics(hass, entry) -> dict[str, object]`.
- Produces: user-facing installation and troubleshooting documentation.

- [ ] **Step 1: Write failing diagnostics tests**

Create `tests/test_diagnostics.py`:

```python
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
```

- [ ] **Step 2: Run diagnostics tests to verify they fail**

Run: `pytest tests/test_diagnostics.py -v`

Expected: FAIL because `diagnostics.py` does not exist.

- [ ] **Step 3: Add diagnostics implementation**

Create `custom_components/fitorb/diagnostics.py`:

```python
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant

from .const import DOMAIN


def _redact_address(address: str) -> str:
    parts = address.split(":")
    if len(parts) != 6:
        return "***"
    return ":".join(parts[:3] + ["***"])


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a Fitorb config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data
    return {
        "entry_title": entry.title,
        "address": _redact_address(entry.data[CONF_ADDRESS]),
        "available": data.available if data else False,
        "last_successful_update": data.last_successful_update.isoformat()
        if data and data.last_successful_update
        else None,
        "last_error": data.last_error if data else None,
        "unknown_notifications": data.unknown_notifications if data else 0,
        "malformed_notifications": data.malformed_notifications if data else 0,
    }
```

- [ ] **Step 4: Add README**

Create `README.md`:

```markdown
# Fitorb Smart Ring for Home Assistant

Custom Home Assistant integration for Fitorb smart rings that appear compatible with the Colmi R02-R06 BLE protocol.

## Scope

Version 1 exposes current values as Home Assistant entities:

- Battery level
- Charging state
- Steps today
- Calories today
- Distance today
- Heart rate
- SpO2
- Stress
- Last successful update
- Connection state

Historical sync and sleep import are intentionally not included in Version 1.

## Bluetooth Requirements

Home Assistant must be able to make active BLE GATT connections to the ring. A Shelly Bluetooth proxy is not enough for this integration because Shelly devices forward advertisements but do not proxy active GATT connections.

For Home Assistant in Proxmox:

1. Plug a supported USB Bluetooth adapter into the Proxmox host.
2. Pass the USB device through to the Home Assistant VM.
3. Restart the VM.
4. In Home Assistant, add or verify the Bluetooth integration.
5. Disconnect the ring from the phone app before first setup if the ring only accepts one active BLE connection.

## Installation

Copy `custom_components/fitorb` into Home Assistant's `custom_components` directory or add this repository as a HACS custom repository.

Restart Home Assistant, then add **Fitorb Smart Ring** from **Settings > Devices & services**.

## Debug Logging

Add this to `configuration.yaml` when collecting logs:

```yaml
logger:
  logs:
    custom_components.fitorb: debug
```

Debug logs may include raw BLE notification payloads in hexadecimal form.

## Known Limits

- The phone app may need to be disconnected while Home Assistant polls the ring.
- Calories and distance units should be verified against real ring data.
- Unknown BLE packets are logged for analysis and ignored by Version 1.
```

- [ ] **Step 5: Expand translation entity names**

Replace the config translation files with content that includes entity names. For `strings.json` and `translations/en.json`, use:

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Set up Fitorb Smart Ring",
        "description": "Enter the Bluetooth address of the ring.",
        "data": {
          "address": "Bluetooth address",
          "name": "Name"
        }
      },
      "bluetooth_confirm": {
        "title": "Set up {name}",
        "description": "Add this Fitorb/Colmi-compatible smart ring to Home Assistant?"
      }
    },
    "error": {
      "invalid_address": "Enter a Bluetooth MAC address such as AA:BB:CC:DD:EE:FF."
    },
    "abort": {
      "already_configured": "This ring is already configured.",
      "no_discovery_info": "Bluetooth discovery information is no longer available."
    }
  },
  "entity": {
    "sensor": {
      "battery_level": { "name": "Battery" },
      "steps": { "name": "Steps today" },
      "calories": { "name": "Calories today" },
      "distance": { "name": "Distance today" },
      "heart_rate": { "name": "Heart rate" },
      "spo2": { "name": "SpO2" },
      "stress": { "name": "Stress" },
      "last_successful_update": { "name": "Last successful update" }
    },
    "binary_sensor": {
      "is_charging": { "name": "Charging" },
      "connection_state": { "name": "Connection" }
    }
  }
}
```

For `translations/de.json`, use:

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Fitorb Smart Ring einrichten",
        "description": "Gib die Bluetooth-Adresse des Rings ein.",
        "data": {
          "address": "Bluetooth-Adresse",
          "name": "Name"
        }
      },
      "bluetooth_confirm": {
        "title": "{name} einrichten",
        "description": "Diesen Fitorb-/Colmi-kompatiblen Smart Ring zu Home Assistant hinzufügen?"
      }
    },
    "error": {
      "invalid_address": "Gib eine Bluetooth-MAC-Adresse wie AA:BB:CC:DD:EE:FF ein."
    },
    "abort": {
      "already_configured": "Dieser Ring ist bereits eingerichtet.",
      "no_discovery_info": "Die Bluetooth-Erkennungsdaten sind nicht mehr verfügbar."
    }
  },
  "entity": {
    "sensor": {
      "battery_level": { "name": "Akku" },
      "steps": { "name": "Schritte heute" },
      "calories": { "name": "Kalorien heute" },
      "distance": { "name": "Distanz heute" },
      "heart_rate": { "name": "Herzfrequenz" },
      "spo2": { "name": "SpO2" },
      "stress": { "name": "Stress" },
      "last_successful_update": { "name": "Letzte erfolgreiche Aktualisierung" }
    },
    "binary_sensor": {
      "is_charging": { "name": "Lädt" },
      "connection_state": { "name": "Verbindung" }
    }
  }
}
```

- [ ] **Step 6: Run all tests**

Run: `pytest -v`

Expected: PASS.

- [ ] **Step 7: Run lint**

Run: `ruff check .`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add README.md custom_components/fitorb/diagnostics.py custom_components/fitorb/strings.json custom_components/fitorb/translations tests/test_diagnostics.py
git commit -m "docs: add fitorb diagnostics and setup guide"
```

---

## Manual Hardware Validation

Run this after the code tasks pass.

- [ ] Pass the USB Bluetooth adapter through from Proxmox to the Home Assistant VM.
- [ ] Confirm Home Assistant shows the Bluetooth integration with a usable adapter.
- [ ] Disconnect the ring from the phone app.
- [ ] Restart Home Assistant after installing the custom integration.
- [ ] Add the integration through **Settings > Devices & services**.
- [ ] Confirm battery, charging, steps, calories, distance, and at least one active health metric update.
- [ ] Move the ring out of range or reconnect it to the phone app.
- [ ] Confirm entities become unavailable without requiring an integration reload.
- [ ] Reconnect the ring to Home Assistant.
- [ ] Confirm the next update recovers.

## Self-Review Notes

- Spec coverage: Tasks cover HACS metadata, BLE command construction, notification parsing, config flow, active polling, entities, diagnostics, README, tests, and manual Proxmox/Bluetooth validation.
- Deferred scope: Historical sync, sleep import, and continuous raw recording are excluded from all tasks.
- Type consistency: `FitorbData`, `ParsedNotification`, `FitorbBleClient.async_read_current_data`, and `FitorbDataUpdateCoordinator` are defined before use by later tasks.
