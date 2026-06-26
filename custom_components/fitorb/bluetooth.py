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
                await client.write_gatt_char(
                    CMD_WRITE_CHAR_UUID,
                    build_command(command),
                )
                snapshot = await self._drain_notifications(queue, snapshot)
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
