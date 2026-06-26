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
