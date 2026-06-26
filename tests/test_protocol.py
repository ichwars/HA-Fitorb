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
    parsed = parse_notification(
        bytes([0x03, 71, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 75])
    )

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
    parsed = parse_notification(
        bytes([0x69, 0x01, 0x01, 64, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 207])
    )

    assert parsed is not None
    assert parsed.kind is NotificationKind.HEART_RATE
    assert parsed.values == {"heart_rate": 64, "running": False}


def test_parse_spo2_result() -> None:
    parsed = parse_notification(
        bytes([0x69, 0x03, 0x01, 98, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 5])
    )

    assert parsed is not None
    assert parsed.kind is NotificationKind.SPO2
    assert parsed.values == {"spo2": 98, "running": False}


def test_parse_stress_result() -> None:
    parsed = parse_notification(
        bytes([0x69, 0x08, 0x01, 32, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 164])
    )

    assert parsed is not None
    assert parsed.kind is NotificationKind.STRESS
    assert parsed.values == {"stress": 32, "running": False}


def test_parse_unknown_notification_returns_none() -> None:
    assert (
        parse_notification(
            bytes([0x99, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        )
        is None
    )
