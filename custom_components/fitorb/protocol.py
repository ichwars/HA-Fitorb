from __future__ import annotations

from .models import NotificationKind, ParsedNotification

COMMAND_BATTERY = "03"
COMMAND_SET_METRIC_UNITS = "0a0200"
COMMAND_ACTIVITY = "43000f005f01"
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


def _bcd_to_decimal(value: int) -> int:
    return (((value >> 4) & 0x0F) * 10) + (value & 0x0F)


class ActivityLogParser:
    """Parse the multi-packet Colmi 0x43 steps log response."""

    def __init__(self) -> None:
        self._reset()

    def _reset(self) -> None:
        self._new_calorie_protocol = False
        self._steps = 0
        self._calories_raw = 0
        self._distance = 0

    def parse(self, data: bytes | bytearray) -> ParsedNotification | None:
        """Return an activity notification when the 0x43 response is complete."""
        payload = bytes(data)
        if not _ensure_16(payload) or payload[0] != 0x43:
            return None

        if payload[1] == 0xFF:
            self._reset()
            return ParsedNotification(
                kind=NotificationKind.ACTIVITY,
                values={"steps": 0, "calories": 0, "distance": 0},
                raw_hex=payload.hex(),
            )

        if payload[1] == 0xF0:
            self._new_calorie_protocol = payload[3] == 0x01
            return None

        month = _bcd_to_decimal(payload[2])
        day = _bcd_to_decimal(payload[3])
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return None

        calories = payload[7] | (payload[8] << 8)
        if self._new_calorie_protocol:
            calories *= 10
        self._calories_raw += calories
        self._steps += payload[9] | (payload[10] << 8)
        self._distance += payload[11] | (payload[12] << 8)

        is_last_packet = payload[5] == payload[6] - 1
        if not is_last_packet:
            return None

        values = {
            "steps": self._steps,
            "calories": self._calories_raw // 1000,
            "distance": self._distance,
        }
        self._reset()
        return ParsedNotification(
            kind=NotificationKind.ACTIVITY,
            values=values,
            raw_hex=payload.hex(),
        )


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

    if payload[0] == 0x0A:
        return ParsedNotification(
            kind=NotificationKind.UNITS_PREFERENCE,
            values={"metric": payload[1] == 0x02},
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
