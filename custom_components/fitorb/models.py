from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import StrEnum
from typing import Any


class NotificationKind(StrEnum):
    """Known ring notification classes."""

    BATTERY = "battery"
    UNITS_PREFERENCE = "units_preference"
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


class HistoryMetric(StrEnum):
    """Historical sample metric names."""

    STEPS = "steps"
    CALORIES = "calories"
    DISTANCE = "distance"
    HEART_RATE = "heart_rate"
    SPO2 = "spo2"
    STRESS = "stress"
    SLEEP_STAGE = "sleep_stage"


@dataclass(frozen=True, slots=True)
class FitorbHistorySample:
    """One timestamped historical ring value."""

    metric: HistoryMetric
    timestamp: datetime
    value: int | float | str
    source_day: date
    raw_hex: str | None = None


@dataclass(frozen=True, slots=True)
class FitorbHistoryResult:
    """Result of one historical sync attempt."""

    samples: tuple[FitorbHistorySample, ...] = ()
    status: str = "idle"
    requested_days: int = 0
    first_sample: datetime | None = None
    last_sample: datetime | None = None
    unknown_packets: int = 0
    malformed_packets: int = 0


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
    last_history_sync: datetime | None = None
    last_history_sample_count: int | None = None
    last_history_status: str | None = None
    last_history_first_sample: datetime | None = None
    last_history_last_sample: datetime | None = None
    history_unknown_packets: int = 0
    history_malformed_packets: int = 0
    unknown_notifications: int = 0
    malformed_notifications: int = 0

    def with_values(self, **values: Any) -> FitorbData:
        """Return a copy with updated values."""
        return replace(self, **values)


@dataclass(frozen=True, slots=True)
class FitorbReadResult:
    """Live data plus optional historical samples from one BLE session."""

    data: FitorbData
    history: FitorbHistoryResult | None = None
