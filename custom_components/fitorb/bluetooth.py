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
    ActivityLogParser,
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
_HEALTH_NOTIFICATION_KINDS = {
    NotificationKind.HEART_RATE,
    NotificationKind.SPO2,
    NotificationKind.STRESS,
}


class FitorbBluetoothError(Exception):
    """Base exception for Fitorb Bluetooth failures."""


class FitorbDeviceUnavailable(FitorbBluetoothError):
    """Raised when no connectable BLE device is available."""


class FitorbResponseTimeout(FitorbBluetoothError):
    """Raised when the ring does not send the expected command response."""


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

    async def async_read_current_data(
        self,
        base: FitorbData,
        *,
        include_health: bool = True,
    ) -> FitorbData:
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
            await client.write_gatt_char(
                CMD_WRITE_CHAR_UUID,
                build_command(COMMAND_BATTERY),
            )
            snapshot = await self._drain_until_expected(
                queue,
                snapshot,
                expected_kind=NotificationKind.BATTERY,
            )
            await client.write_gatt_char(
                CMD_WRITE_CHAR_UUID,
                build_command(COMMAND_SET_METRIC_UNITS),
            )
            await client.write_gatt_char(
                CMD_WRITE_CHAR_UUID,
                build_command(COMMAND_ACTIVITY),
            )
            snapshot = await self._drain_optional_response(
                queue,
                snapshot,
                expected_kind=NotificationKind.ACTIVITY,
            )
            if include_health:
                for command, expected_kind in (
                    (COMMAND_HEART_RATE, NotificationKind.HEART_RATE),
                    (COMMAND_SPO2, NotificationKind.SPO2),
                    (COMMAND_STRESS, NotificationKind.STRESS),
                ):
                    await client.write_gatt_char(
                        CMD_WRITE_CHAR_UUID,
                        build_command(command),
                    )
                    snapshot = await self._drain_optional_response(
                        queue,
                        snapshot,
                        expected_kind=expected_kind,
                    )
            return snapshot
        finally:
            try:
                await client.stop_notify(CMD_NOTIFY_CHAR_UUID)
            except Exception:
                _LOGGER.debug("Unable to stop Fitorb notifications", exc_info=True)
            try:
                await client.disconnect()
            except Exception:
                _LOGGER.debug("Unable to disconnect Fitorb client", exc_info=True)

    async def _drain_optional_response(
        self,
        queue: asyncio.Queue[bytes],
        snapshot: FitorbData,
        *,
        expected_kind: NotificationKind,
    ) -> FitorbData:
        """Drain an optional command response without failing the whole snapshot."""
        try:
            return await self._drain_until_expected(
                queue,
                snapshot,
                expected_kind=expected_kind,
            )
        except FitorbResponseTimeout:
            _LOGGER.debug(
                "No Fitorb %s response; keeping other current values",
                expected_kind.value,
                exc_info=True,
            )
            return snapshot

    async def _drain_until_expected(
        self,
        queue: asyncio.Queue[bytes],
        snapshot: FitorbData,
        *,
        expected_kind: NotificationKind | str,
    ) -> FitorbData:
        """Drain notifications until the expected response is received."""
        expected = NotificationKind(expected_kind)
        activity_log_parser = (
            ActivityLogParser() if expected is NotificationKind.ACTIVITY else None
        )
        end_time = self.hass.loop.time() + self.response_timeout
        while self.hass.loop.time() < end_time:
            timeout = max(0.1, end_time - self.hass.loop.time())
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=timeout)
            except TimeoutError:
                break
            if len(payload) != 16:
                _LOGGER.debug("Malformed Fitorb notification: %s", payload.hex())
                snapshot = snapshot.with_values(
                    malformed_notifications=snapshot.malformed_notifications + 1
                )
                continue
            parsed = parse_notification(payload)
            if (
                parsed is None
                and activity_log_parser is not None
                and payload[0] == 0x43
            ):
                parsed = activity_log_parser.parse(payload)
                if parsed is None:
                    continue
            if parsed is None:
                _LOGGER.debug("Unknown Fitorb notification: %s", payload.hex())
                snapshot = snapshot.with_values(
                    unknown_notifications=snapshot.unknown_notifications + 1
                )
                continue
            snapshot = _apply_notification(snapshot, parsed.kind, parsed.values)
            if _is_expected_response(parsed.kind, parsed.values, expected):
                return snapshot
        _LOGGER.debug("No Fitorb %s response before command timeout", expected.value)
        raise FitorbResponseTimeout(
            f"Timed out waiting for Fitorb {expected.value.replace('_', ' ')} response"
        )


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


def _is_expected_response(
    kind: NotificationKind,
    values: dict[str, object],
    expected_kind: NotificationKind,
) -> bool:
    """Return whether a parsed notification completes the expected command."""
    if kind is not expected_kind:
        return False
    if expected_kind in _HEALTH_NOTIFICATION_KINDS:
        return values.get("running") is False
    return True
