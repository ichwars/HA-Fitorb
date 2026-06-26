from __future__ import annotations

import asyncio
from datetime import date
import logging

from bleak import BleakClient
from bleak_retry_connector import establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .const import (
    CMD_NOTIFY_CHAR_UUID,
    CMD_WRITE_CHAR_UUID,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_HEALTH_MEASUREMENT_TIMEOUT,
    DEFAULT_HEALTH_RESPONSE_TIMEOUT,
    DEFAULT_RESPONSE_TIMEOUT,
    RAW_NOTIFY_CHAR_UUID,
    RAW_WRITE_CHAR_UUID,
)
from .history_protocol import (
    BIG_DATA_SLEEP_ID,
    BigDataFrame,
    BigDataFrameParser,
    build_big_data_request,
    build_heart_rate_history_command,
    parse_heart_rate_history_packets,
    parse_sleep_history_payload,
)
from .models import (
    FitorbData,
    FitorbHistoryRequest,
    FitorbHistoryResult,
    FitorbHistorySample,
    FitorbReadResult,
    FitorbSleepSummary,
    NotificationKind,
)
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
_HEALTH_VALUE_KEYS = {
    NotificationKind.HEART_RATE: "heart_rate",
    NotificationKind.SPO2: "spo2",
    NotificationKind.STRESS: "stress",
}


class FitorbBluetoothError(Exception):
    """Base exception for Fitorb Bluetooth failures."""


class FitorbDeviceUnavailable(FitorbBluetoothError):
    """Raised when no connectable BLE device is available."""


class FitorbResponseTimeout(FitorbBluetoothError):
    """Raised when the ring does not send the expected command response."""


class FitorbBleSessionUnavailable(FitorbBluetoothError):
    """Raised internally when the current GATT session is no longer usable."""


class FitorbBleClient:
    """Read current data from a Fitorb/Colmi-compatible ring."""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        *,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        response_timeout: float = DEFAULT_RESPONSE_TIMEOUT,
        health_response_timeout: float = DEFAULT_HEALTH_RESPONSE_TIMEOUT,
        health_measurement_timeout: float = DEFAULT_HEALTH_MEASUREMENT_TIMEOUT,
    ) -> None:
        self.hass = hass
        self.address = address
        self.connect_timeout = connect_timeout
        self.response_timeout = response_timeout
        self.health_response_timeout = health_response_timeout
        self.health_measurement_timeout = health_measurement_timeout

    async def async_read_current_data(
        self,
        base: FitorbData,
        *,
        include_health: bool = True,
    ) -> FitorbData:
        """Connect to the ring and read the Version 1 current values."""
        result = await self.async_read_current_data_with_history(
            base,
            include_health=include_health,
            history_request=None,
        )
        return result.data

    async def async_read_current_data_with_history(
        self,
        base: FitorbData,
        *,
        include_health: bool = True,
        history_request: FitorbHistoryRequest | None = None,
    ) -> FitorbReadResult:
        """Connect to the ring and read current values plus optional history."""
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

        try:
            client = await establish_connection(
                BleakClient,
                ble_device,
                self.address,
                timeout=self.connect_timeout,
            )
        except Exception as err:
            if _is_ble_connection_unavailable_error(err):
                raise FitorbDeviceUnavailable(str(err)) from err
            raise
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
            history_result = None
            try:
                await self._write_optional_command(
                    client,
                    COMMAND_SET_METRIC_UNITS,
                    description="metric units",
                )
                snapshot = await self._read_optional_command(
                    client,
                    queue,
                    snapshot,
                    command=COMMAND_ACTIVITY,
                    expected_kind=NotificationKind.ACTIVITY,
                )
                if include_health and snapshot.is_charging is True:
                    _LOGGER.debug(
                        "Skipping Fitorb health reads because the ring is charging"
                    )
                elif include_health:
                    for command, expected_kind in (
                        (COMMAND_HEART_RATE, NotificationKind.HEART_RATE),
                        (COMMAND_SPO2, NotificationKind.SPO2),
                        (COMMAND_STRESS, NotificationKind.STRESS),
                    ):
                        snapshot = await self._read_optional_command(
                            client,
                            queue,
                            snapshot,
                            command=command,
                            expected_kind=expected_kind,
                        )
                if history_request is not None:
                    history_result = await self._read_history(
                        queue,
                        client,
                        history_request,
                    )
            except FitorbBleSessionUnavailable as err:
                _LOGGER.debug(
                    "Skipping remaining Fitorb optional reads because the BLE "
                    "session is no longer usable: %s",
                    err,
                )
            return FitorbReadResult(data=snapshot, history=history_result)
        finally:
            try:
                await client.stop_notify(CMD_NOTIFY_CHAR_UUID)
            except Exception as err:
                _LOGGER.debug("Unable to stop Fitorb notifications: %s", err)
            try:
                await client.disconnect()
            except Exception as err:
                _LOGGER.debug("Unable to disconnect Fitorb client: %s", err)

    async def _write_optional_command(
        self,
        client: BleakClient,
        command: str,
        *,
        description: str,
    ) -> None:
        """Write a best-effort command that is not required for availability."""
        try:
            await client.write_gatt_char(CMD_WRITE_CHAR_UUID, build_command(command))
        except Exception as err:
            _LOGGER.debug("Unable to request optional Fitorb %s: %s", description, err)
            if _is_ble_session_unavailable_error(err):
                raise FitorbBleSessionUnavailable(str(err)) from err

    async def _read_optional_command(
        self,
        client: BleakClient,
        queue: asyncio.Queue[bytes],
        snapshot: FitorbData,
        *,
        command: str,
        expected_kind: NotificationKind,
    ) -> FitorbData:
        """Write and drain an optional command without losing current values."""
        try:
            payload = build_command(command)
            _LOGGER.debug(
                "Requesting optional Fitorb %s data with command %s",
                expected_kind.value,
                payload.hex(),
            )
            await client.write_gatt_char(CMD_WRITE_CHAR_UUID, payload)
        except Exception as err:
            _LOGGER.debug(
                "Unable to request optional Fitorb %s data; keeping current values: %s",
                expected_kind.value,
                err,
            )
            if _is_ble_session_unavailable_error(err):
                raise FitorbBleSessionUnavailable(str(err)) from err
            return snapshot
        return await self._drain_optional_response(
            queue,
            snapshot,
            expected_kind=expected_kind,
            response_timeout=(
                self.health_response_timeout
                if expected_kind in _HEALTH_NOTIFICATION_KINDS
                else self.response_timeout
            ),
            measurement_timeout=(
                self.health_measurement_timeout
                if expected_kind in _HEALTH_NOTIFICATION_KINDS
                else None
            ),
        )

    async def _drain_optional_response(
        self,
        queue: asyncio.Queue[bytes],
        snapshot: FitorbData,
        *,
        expected_kind: NotificationKind,
        response_timeout: float | None = None,
        measurement_timeout: float | None = None,
    ) -> FitorbData:
        """Drain an optional command response without failing the whole snapshot."""
        if (
            response_timeout is None
            and expected_kind in _HEALTH_NOTIFICATION_KINDS
        ):
            response_timeout = self.health_response_timeout
        if (
            measurement_timeout is None
            and expected_kind in _HEALTH_NOTIFICATION_KINDS
        ):
            measurement_timeout = self.health_measurement_timeout
        try:
            return await self._drain_until_expected(
                queue,
                snapshot,
                expected_kind=expected_kind,
                response_timeout=response_timeout,
                measurement_timeout=measurement_timeout,
                log_timeout=False,
            )
        except FitorbResponseTimeout:
            _LOGGER.debug(
                "No Fitorb %s response; keeping other current values",
                expected_kind.value,
            )
            return snapshot

    async def _read_history(
        self,
        queue: asyncio.Queue[bytes],
        client: BleakClient,
        request: FitorbHistoryRequest,
    ) -> FitorbHistoryResult:
        """Read supported history packet families without failing live values."""
        samples = []
        unknown_packets = 0
        malformed_packets = 0
        sleep_summary: FitorbSleepSummary | None = None
        session_error: Exception | None = None
        status = "success"
        for target_day in request.days:
            try:
                await client.write_gatt_char(
                    CMD_WRITE_CHAR_UUID,
                    build_heart_rate_history_command(target_day),
                )
                packets, completed, day_unknown_packets, day_malformed_packets = (
                    await self._drain_history_packets(
                        queue,
                        expected_command=0x15,
                    )
                )
                unknown_packets += day_unknown_packets
                malformed_packets += day_malformed_packets
                if not completed:
                    status = "partial"
                try:
                    samples.extend(parse_heart_rate_history_packets(packets))
                except Exception as err:
                    _LOGGER.debug(
                        "Unable to parse Fitorb heart_rate history for %s: %s",
                        target_day.isoformat(),
                        err,
                    )
                    status = "partial"
            except Exception as err:
                if _is_ble_session_unavailable_error(err):
                    _LOGGER.debug(
                        "Stopping Fitorb history because the BLE session is no "
                        "longer usable: %s",
                        err,
                    )
                    session_error = err
                    status = "partial"
                    break
                _LOGGER.debug(
                    "Unable to read Fitorb heart_rate history for %s: %s",
                    target_day.isoformat(),
                    err,
                )
                status = "partial"
                continue
        if session_error is None:
            try:
                sleep_samples, sleep_summary, sleep_unknown, sleep_malformed = (
                    await self._read_sleep_history(client)
                )
                samples.extend(sleep_samples)
                unknown_packets += sleep_unknown
                malformed_packets += sleep_malformed
            except Exception as err:
                if _is_ble_session_unavailable_error(err):
                    _LOGGER.debug(
                        "Stopping Fitorb sleep history because the BLE session "
                        "is no longer usable: %s",
                        err,
                    )
                    session_error = err
                else:
                    _LOGGER.debug("Unable to read Fitorb sleep history: %s", err)
                status = "partial"

        ordered = tuple(sorted(samples, key=lambda sample: sample.timestamp))
        if (
            session_error is not None
            and not ordered
            and sleep_summary is None
            and unknown_packets == 0
            and malformed_packets == 0
        ):
            raise FitorbBleSessionUnavailable(str(session_error)) from session_error
        return FitorbHistoryResult(
            samples=ordered,
            status=status,
            requested_days=len(request.days),
            first_sample=ordered[0].timestamp if ordered else None,
            last_sample=ordered[-1].timestamp if ordered else None,
            sleep_summary=sleep_summary,
            unknown_packets=unknown_packets,
            malformed_packets=malformed_packets,
        )

    async def _read_sleep_history(
        self,
        client: BleakClient,
    ) -> tuple[list[FitorbHistorySample], FitorbSleepSummary | None, int, int]:
        """Read Colmi Big Data sleep history from the raw GATT service."""
        raw_queue: asyncio.Queue[bytes] = asyncio.Queue()

        def _raw_notification_handler(_sender: int, data: bytearray) -> None:
            raw_queue.put_nowait(bytes(data))

        await client.start_notify(RAW_NOTIFY_CHAR_UUID, _raw_notification_handler)
        try:
            await client.write_gatt_char(
                RAW_WRITE_CHAR_UUID,
                build_big_data_request(BIG_DATA_SLEEP_ID),
            )
            frames, unknown_packets, malformed_packets = (
                await self._drain_big_data_frames(
                    raw_queue,
                    expected_data_id=BIG_DATA_SLEEP_ID,
                )
            )
            samples: list[FitorbHistorySample] = []
            summary = None
            today = date.today()
            for frame in frames:
                parsed = parse_sleep_history_payload(frame.payload, today=today)
                samples.extend(parsed.samples)
                if parsed.summary is not None and (
                    summary is None or parsed.summary.start > summary.start
                ):
                    summary = parsed.summary
            return samples, summary, unknown_packets, malformed_packets
        finally:
            try:
                await client.stop_notify(RAW_NOTIFY_CHAR_UUID)
            except Exception as err:
                _LOGGER.debug("Unable to stop Fitorb raw notifications: %s", err)

    async def _drain_until_expected(
        self,
        queue: asyncio.Queue[bytes],
        snapshot: FitorbData,
        *,
        expected_kind: NotificationKind | str,
        response_timeout: float | None = None,
        measurement_timeout: float | None = None,
        log_timeout: bool = True,
    ) -> FitorbData:
        """Drain notifications until the expected response is received."""
        expected = NotificationKind(expected_kind)
        activity_log_parser = (
            ActivityLogParser() if expected is NotificationKind.ACTIVITY else None
        )
        timeout_seconds = self.response_timeout
        if response_timeout is not None:
            timeout_seconds = response_timeout
        start_time = self.hass.loop.time()
        end_time = start_time + timeout_seconds
        measurement_deadline = (
            start_time + measurement_timeout
            if measurement_timeout is not None
            else None
        )
        measurement_deadline_enabled = False
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
            if (
                parsed.kind is expected
                and _is_health_response_without_value(
                    parsed.kind,
                    parsed.values,
                )
            ):
                _LOGGER.debug(
                    "Fitorb %s response did not include a value yet: %s",
                    parsed.kind.value,
                    parsed.raw_hex,
                )
                if (
                    measurement_deadline is not None
                    and not measurement_deadline_enabled
                ):
                    end_time = max(end_time, measurement_deadline)
                    measurement_deadline_enabled = True
                continue
            if _is_expected_response(parsed.kind, parsed.values, expected):
                return snapshot
            if (
                parsed.kind is expected
                and parsed.values.get("running") is True
                and measurement_deadline is not None
                and not measurement_deadline_enabled
            ):
                end_time = max(end_time, measurement_deadline)
                measurement_deadline_enabled = True
        if log_timeout:
            _LOGGER.debug(
                "No Fitorb %s response before command timeout",
                expected.value,
            )
        raise FitorbResponseTimeout(
            f"Timed out waiting for Fitorb {expected.value.replace('_', ' ')} response"
        )

    async def _drain_history_packets(
        self,
        queue: asyncio.Queue[bytes],
        *,
        expected_command: int,
    ) -> tuple[list[bytes], bool, int, int]:
        """Drain history packets until a parser-visible end or timeout."""
        packets: list[bytes] = []
        unknown_packets = 0
        malformed_packets = 0
        completed = False
        end_time = self.hass.loop.time() + self.response_timeout
        while self.hass.loop.time() < end_time:
            timeout = max(0.1, end_time - self.hass.loop.time())
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=timeout)
            except TimeoutError:
                break
            if len(payload) != 16:
                _LOGGER.debug("Malformed Fitorb history notification: %s", payload.hex())
                malformed_packets += 1
                continue
            if payload[0] != expected_command:
                _LOGGER.debug("Unknown Fitorb history notification: %s", payload.hex())
                unknown_packets += 1
                continue
            packets.append(payload)
            if payload[1] == 0xFF:
                completed = True
                break
            if payload[1] > 0 and packets and packets[0][1] == 0:
                expected_packets = packets[0][2]
                if expected_packets and payload[1] >= expected_packets - 1:
                    completed = True
                    break
        return packets, completed, unknown_packets, malformed_packets

    async def _drain_big_data_frames(
        self,
        queue: asyncio.Queue[bytes],
        *,
        expected_data_id: int,
    ) -> tuple[list[BigDataFrame], int, int]:
        """Drain raw Big Data frames until an expected frame or timeout."""
        parser = BigDataFrameParser()
        frames: list[BigDataFrame] = []
        unknown_packets = 0
        malformed_packets = 0
        end_time = self.hass.loop.time() + self.response_timeout
        while self.hass.loop.time() < end_time:
            timeout = max(0.1, end_time - self.hass.loop.time())
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=timeout)
            except TimeoutError:
                break
            if not payload:
                malformed_packets += 1
                continue
            parsed_frames = parser.consume(payload)
            if not parsed_frames and payload[0] != 0xBC:
                malformed_packets += 1
                continue
            for frame in parsed_frames:
                if frame.data_id == expected_data_id:
                    frames.append(frame)
                else:
                    unknown_packets += 1
            if frames:
                return frames, unknown_packets, malformed_packets
        if frames or unknown_packets or malformed_packets:
            return frames, unknown_packets, malformed_packets
        raise FitorbResponseTimeout("Timed out waiting for Fitorb sleep history")


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
    if kind is NotificationKind.UNITS_PREFERENCE:
        return snapshot
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
        return (
            values.get("running") is False
            and not _is_health_response_without_value(kind, values)
        )
    return True


def _is_health_response_without_value(
    kind: NotificationKind,
    values: dict[str, object],
) -> bool:
    """Return whether a health command completed without a measured value."""
    value_key = _HEALTH_VALUE_KEYS.get(kind)
    return value_key is not None and values.get(value_key) is None


def _is_ble_session_unavailable_error(err: Exception) -> bool:
    """Return whether an exception means the current BLE session is unusable."""
    message = str(err).lower()
    return any(
        marker in message
        for marker in (
            "service discovery has not been performed",
            "not connected",
            "device is not connected",
            "disconnected",
            "org.bluez.error.notconnected",
        )
    )


def _is_ble_connection_unavailable_error(err: Exception) -> bool:
    """Return whether an exception means no connectable BLE path is available."""
    message = str(err).lower()
    return any(
        marker in message
        for marker in (
            "no backend with an available connection slot",
            "out of connection slots",
            "device is no longer reachable",
        )
    )
