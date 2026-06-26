# Fitorb History Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a conservative historical sync path that reads cached Fitorb/Colmi ring samples over BLE when the ring returns to Home Assistant range.

**Architecture:** Keep historical protocol parsing separate from the stable live-value parser. Extend the BLE client with an optional same-session history read, persist a per-entry dedupe ledger with Home Assistant's `Store`, and expose validation diagnostics before publishing historical samples into long-term statistics.

**Tech Stack:** Python 3.12, Home Assistant custom integration APIs, Home Assistant Bluetooth helpers, Home Assistant `Store`, Bleak, pytest, pytest-homeassistant-custom-component, Ruff.

## Global Constraints

- Domain remains `fitorb`.
- Live Version 1 sensors must keep working exactly as they do now.
- Home Assistant must have a connectable Bluetooth path to the ring for all direct BLE reads.
- The phone app and Home Assistant mobile app are not BLE GATT relays for this integration.
- Shelly Bluetooth advertisement proxies are not sufficient for active GATT history sync.
- Default history lookback is 7 days.
- History sync uses at least a 1 day overlap window to tolerate missed or partial syncs.
- Unknown historical packets are debug logs and counters only.
- Malformed historical packets are dropped and counted.
- A history timeout must not turn a successful live-value poll into a failed poll.
- Repeated syncs must deduplicate by metric, timestamp, and value.
- The first implementation stores parsed samples and exposes diagnostics; long-term statistics publishing is a follow-up after packet semantics are validated on real hardware.
- Do not write Home Assistant recorder state rows directly.

---

## Source Notes

Use these references while implementing, but keep the code local and unit-tested:

- `CitizenOneX/colmi_r06_fbp`: command names include historical heart rate `0x15`, historical stress `0x37`, historical sleep `0xbc27`, and historical SpO2 `0xbc2a`.
- `YannisDC/ColmiSmartRing`: contains working Swift parsers/tests for heart-rate log packets, split-series pressure/stress packets, and Big Data sleep packets.
- Home Assistant developer docs via Context7: `ConfigEntry` changes use `hass.config_entries.async_update_entry`; persistent custom integration data can use `homeassistant.helpers.storage.Store`.

---

## File Structure

Create these files:

- `custom_components/fitorb/history_protocol.py`: pure history command builders and packet parsers.
- `custom_components/fitorb/history_store.py`: Home Assistant `Store` wrapper for dedupe and sync metadata.
- `tests/test_history_protocol.py`: pure unit tests for history command construction and parsers.
- `tests/test_history_store.py`: store and dedupe tests.

Modify these files:

- `custom_components/fitorb/models.py`: add history sample/result/state dataclasses and diagnostic fields on `FitorbData`.
- `custom_components/fitorb/const.py`: add history option keys and defaults.
- `custom_components/fitorb/bluetooth.py`: add optional same-connection history reads.
- `custom_components/fitorb/coordinator.py`: decide when history is due, persist samples, and keep partial failures quiet.
- `custom_components/fitorb/config_flow.py`: include history defaults and add an options flow.
- `custom_components/fitorb/sensor.py`: add diagnostic sensors for history sync.
- `custom_components/fitorb/diagnostics.py`: include redacted history diagnostics.
- `custom_components/fitorb/strings.json`: add option and sensor labels.
- `custom_components/fitorb/translations/de.json`: add German labels.
- `custom_components/fitorb/translations/en.json`: add English labels.
- `custom_components/fitorb/manifest.json`: bump version to `0.2.0`.
- `README.md`: document history sync, retention uncertainty, and validation workflow.
- `tests/test_config_flow.py`: cover default options and options flow.
- `tests/test_coordinator.py`: cover due logic, store writes, and partial history failures.
- `tests/test_diagnostics.py`: cover new history diagnostics.
- `tests/test_manifest.py`: cover version bump.
- `tests/test_sensor.py`: cover new diagnostic sensors.

---

### Task 1: History Data Models And Pure Protocol

**Files:**
- Create: `custom_components/fitorb/history_protocol.py`
- Create: `tests/test_history_protocol.py`
- Modify: `custom_components/fitorb/models.py`

**Interfaces:**
- Produces: `HistoryMetric(StrEnum)` values `steps`, `calories`, `distance`, `heart_rate`, `spo2`, `stress`, `sleep_stage`.
- Produces: `FitorbHistorySample(metric: HistoryMetric, timestamp: datetime, value: int | float | str, source_day: date, raw_hex: str | None = None)`.
- Produces: `FitorbHistoryResult(samples: tuple[FitorbHistorySample, ...], status: str, requested_days: int, first_sample: datetime | None, last_sample: datetime | None, unknown_packets: int = 0, malformed_packets: int = 0)`.
- Produces: `FitorbReadResult(data: FitorbData, history: FitorbHistoryResult | None = None)`.
- Produces: `build_heart_rate_history_command(target_day: date, tz: tzinfo = UTC) -> bytes`.
- Produces: `build_split_series_history_command(command: int, day_offset: int) -> bytes`.
- Produces: `build_activity_history_command(day_offset: int) -> bytes`.
- Produces: `build_big_data_request(data_id: int) -> bytes`.
- Produces: `parse_heart_rate_history_packets(packets: Iterable[bytes]) -> tuple[FitorbHistorySample, ...]`.
- Produces: `SplitSeriesHistoryParser(metric: HistoryMetric, source_day: date, start_of_day: datetime)`.
- Produces: `BigDataFrameParser.consume(chunk: bytes) -> list[BigDataFrame]`.

- [ ] **Step 1: Write failing protocol tests**

Create `tests/test_history_protocol.py`:

```python
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from custom_components.fitorb.history_protocol import (
    BigDataFrameParser,
    SplitSeriesHistoryParser,
    build_activity_history_command,
    build_big_data_request,
    build_heart_rate_history_command,
    build_split_series_history_command,
    parse_heart_rate_history_packets,
)
from custom_components.fitorb.models import HistoryMetric


def test_build_heart_rate_history_command_uses_midnight_epoch() -> None:
    command = build_heart_rate_history_command(date(2026, 6, 26))

    assert command == bytes(
        [0x15, 0x00, 0xC1, 0x3D, 0x6A, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0x7D]
    )


def test_build_day_offset_history_commands() -> None:
    assert build_split_series_history_command(0x37, 2) == bytes(
        [0x37, 0x02, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0x39]
    )
    assert build_activity_history_command(3) == bytes(
        [0x43, 0x03, 0x0F, 0x00, 0x5F, 0x01, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0xB5]
    )


def test_build_big_data_request_uses_colmi_frame() -> None:
    assert build_big_data_request(0x27) == bytes([0xBC, 0x27, 0, 0, 0xFF, 0xFF])
    assert build_big_data_request(0x2A) == bytes([0xBC, 0x2A, 0, 0, 0xFF, 0xFF])


def test_parse_heart_rate_history_captured_packets() -> None:
    packets = [
        bytes([21, 0, 24, 5, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 50]),
        bytes([21, 1, 128, 105, 142, 105, 91, 0, 0, 0, 0, 0, 94, 0, 0, 175]),
        bytes([21, 2, 0, 0, 0, 61, 0, 0, 0, 0, 0, 58, 0, 0, 0, 142]),
        bytes([21, 3, 0, 0, 55, 0, 0, 0, 0, 0, 60, 0, 0, 0, 0, 139]),
        bytes([21, 4, 0, 68, 0, 0, 0, 0, 0, 56, 0, 0, 0, 0, 0, 149]),
        bytes([21, 5, 67, 0, 0, 0, 0, 0, 62, 0, 0, 0, 0, 0, 69, 224]),
        bytes([21, 6, 0, 0, 0, 0, 0, 57, 0, 0, 0, 0, 0, 98, 0, 182]),
        bytes([21, 7, 0, 0, 0, 0, 73, 0, 0, 0, 0, 0, 62, 0, 0, 163]),
        bytes([21, 8, 0, 0, 0, 99, 0, 0, 0, 0, 0, 68, 0, 0, 0, 196]),
        bytes([21, 9, 0, 0, 85, 0, 0, 0, 0, 0, 93, 0, 0, 0, 0, 208]),
        bytes([21, 10, 0, 87, 0, 0, 0, 0, 0, 81, 0, 0, 0, 0, 0, 199]),
        bytes([21, 11, 85, 0, 0, 0, 0, 0, 94, 0, 0, 0, 0, 0, 77, 32]),
        bytes([21, 12, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 33]),
        bytes([21, 13, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 34]),
        bytes([21, 14, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 35]),
        bytes([21, 15, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 36]),
        bytes([21, 16, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 37]),
        bytes([21, 17, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 38]),
        bytes([21, 18, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 39]),
        bytes([21, 19, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 40]),
        bytes([21, 20, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 41]),
        bytes([21, 21, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 42]),
        bytes([21, 22, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 43]),
        bytes([21, 23, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 44]),
    ]

    samples = parse_heart_rate_history_packets(packets)

    assert len(samples) == 24
    assert samples[0].metric is HistoryMetric.HEART_RATE
    assert samples[0].timestamp == datetime.fromtimestamp(1770940800, UTC)
    assert samples[0].value == 91
    assert samples[1].timestamp == datetime.fromtimestamp(1770940800, UTC) + timedelta(
        minutes=30
    )
    assert [sample.value for sample in samples[:4]] == [91, 94, 61, 58]


def test_split_series_parser_decodes_stress_values() -> None:
    parser = SplitSeriesHistoryParser(
        metric=HistoryMetric.STRESS,
        source_day=date(2026, 6, 26),
        start_of_day=datetime(2026, 6, 26, tzinfo=UTC),
    )

    assert parser.consume(bytes([55, 0, 24, 30, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 92])) is None
    samples = parser.consume(
        bytes([55, 1, 24, 61, 0, 58, 55, 0, 60, 68, 56, 67, 62, 69, 224])
    )

    assert samples is not None
    assert [sample.value for sample in samples[:3]] == [61, 58, 55]
    assert samples[0].timestamp == datetime(2026, 6, 26, tzinfo=UTC)
    assert samples[1].timestamp == datetime(2026, 6, 26, 1, 0, tzinfo=UTC)


def test_big_data_frame_parser_reassembles_chunked_sleep_response() -> None:
    parser = BigDataFrameParser()
    payload = bytes([2, 1, 8, 100, 5, 200, 1, 2, 30, 3, 18])
    frame = bytes([0xBC, 0x27, len(payload), 0, 0x79, 0xED]) + payload

    assert parser.consume(frame[:4]) == []
    frames = parser.consume(frame[4:])

    assert len(frames) == 1
    assert frames[0].data_id == 0x27
    assert frames[0].payload == payload
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_history_protocol.py -v`

Expected: FAIL with import errors for `custom_components.fitorb.history_protocol` and missing history model types.

- [ ] **Step 3: Add history models**

Modify `custom_components/fitorb/models.py` by adding these imports:

```python
from datetime import date, datetime
from enum import StrEnum
```

Add these types after `ParsedNotification`:

```python
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
class FitorbReadResult:
    """Live data plus optional historical samples from one BLE session."""

    data: FitorbData
    history: FitorbHistoryResult | None = None
```

Extend `FitorbData` with:

```python
    last_history_sync: datetime | None = None
    last_history_sample_count: int | None = None
    last_history_status: str | None = None
    last_history_first_sample: datetime | None = None
    last_history_last_sample: datetime | None = None
    history_unknown_packets: int = 0
    history_malformed_packets: int = 0
```

- [ ] **Step 4: Implement pure history protocol**

Create `custom_components/fitorb/history_protocol.py`:

```python
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, tzinfo

from .models import FitorbHistorySample, HistoryMetric
from .protocol import build_command

BIG_DATA_MAGIC = 0xBC
BIG_DATA_SLEEP_ID = 0x27
BIG_DATA_SPO2_ID = 0x2A
COMMAND_HISTORY_HEART_RATE = 0x15
COMMAND_HISTORY_STRESS = 0x37
COMMAND_HISTORY_ACTIVITY = 0x43


@dataclass(frozen=True, slots=True)
class BigDataFrame:
    """Parsed variable-length Colmi Big Data frame."""

    data_id: int
    data_len: int
    crc16: int
    payload: bytes
    raw_hex: str


def _checksum_packet(payload: bytes) -> bytes:
    command = bytearray(16)
    command[: len(payload)] = payload
    command[15] = sum(command[:15]) & 0xFF
    return bytes(command)


def build_heart_rate_history_command(target_day: date, tz: tzinfo = UTC) -> bytes:
    """Build command 0x15 for one day of 5-minute heart-rate samples."""
    midnight = datetime.combine(target_day, time.min, tzinfo=tz)
    timestamp = int(midnight.timestamp())
    return _checksum_packet(
        bytes([COMMAND_HISTORY_HEART_RATE]) + timestamp.to_bytes(4, "little")
    )


def build_split_series_history_command(command: int, day_offset: int) -> bytes:
    """Build split-series history command such as stress/pressure 0x37."""
    if not 0 <= command <= 0xFF:
        raise ValueError("command must fit in one byte")
    if not 0 <= day_offset <= 0xFF:
        raise ValueError("day_offset must fit in one byte")
    return build_command(f"{command:02x}{day_offset:02x}")


def build_activity_history_command(day_offset: int) -> bytes:
    """Build command 0x43 for activity history by day offset."""
    if not 0 <= day_offset <= 0xFF:
        raise ValueError("day_offset must fit in one byte")
    return build_command(f"43{day_offset:02x}0f005f01")


def build_big_data_request(data_id: int) -> bytes:
    """Build a Colmi Big Data request frame for sleep or SpO2."""
    if not 0 <= data_id <= 0xFF:
        raise ValueError("data_id must fit in one byte")
    return bytes([BIG_DATA_MAGIC, data_id, 0, 0, 0xFF, 0xFF])


def parse_heart_rate_history_packets(
    packets: Iterable[bytes],
) -> tuple[FitorbHistorySample, ...]:
    """Parse command 0x15 heart-rate history packets into non-zero samples."""
    parser = HeartRateHistoryParser()
    samples: tuple[FitorbHistorySample, ...] = ()
    for packet in packets:
        parsed = parser.consume(packet)
        if parsed is not None:
            samples = parsed
    return samples


class HeartRateHistoryParser:
    """Accumulate command 0x15 packets into 5-minute heart-rate samples."""

    def __init__(self) -> None:
        self._expected_packets = 0
        self._range_minutes = 5
        self._timestamp: datetime | None = None
        self._raw: list[int] = []
        self._index = 0
        self._all_packets: list[bytes] = []

    def consume(self, packet: bytes) -> tuple[FitorbHistorySample, ...] | None:
        """Consume one packet and return samples when the response is complete."""
        if len(packet) != 16 or packet[0] != COMMAND_HISTORY_HEART_RATE:
            return None
        self._all_packets.append(packet)
        subtype = packet[1]
        if subtype == 0xFF:
            self._reset()
            return ()
        if subtype == 0:
            self._expected_packets = packet[2]
            self._range_minutes = max(1, packet[3])
            self._raw = []
            self._index = 0
            return None
        if subtype == 1:
            timestamp = int.from_bytes(packet[2:6], "little")
            self._timestamp = datetime.fromtimestamp(timestamp, UTC)
            self._append_values(packet[6:15])
            if self._expected_packets <= 2:
                return self._samples()
            return None
        self._append_values(packet[2:15])
        if self._expected_packets and subtype >= self._expected_packets - 1:
            return self._samples()
        return None

    def _append_values(self, values: bytes) -> None:
        self._raw.extend(int(value) for value in values)
        self._index += len(values)

    def _samples(self) -> tuple[FitorbHistorySample, ...]:
        if self._timestamp is None:
            self._reset()
            return ()
        samples: list[FitorbHistorySample] = []
        source_day = self._timestamp.date()
        for index, value in enumerate(self._raw[:288]):
            if value <= 0:
                continue
            samples.append(
                FitorbHistorySample(
                    metric=HistoryMetric.HEART_RATE,
                    timestamp=self._timestamp + _minutes(index * self._range_minutes),
                    value=value,
                    source_day=source_day,
                    raw_hex=None,
                )
            )
        self._reset()
        return tuple(samples)

    def _reset(self) -> None:
        self._expected_packets = 0
        self._range_minutes = 5
        self._timestamp = None
        self._raw = []
        self._index = 0
        self._all_packets = []


def _minutes(value: int):
    from datetime import timedelta

    return timedelta(minutes=value)


class SplitSeriesHistoryParser:
    """Parse split-array series packets used by stress/pressure history."""

    def __init__(
        self,
        *,
        metric: HistoryMetric,
        source_day: date,
        start_of_day: datetime,
    ) -> None:
        self.metric = metric
        self.source_day = source_day
        self.start_of_day = start_of_day
        self.expected_count = 0
        self.range_minutes = 30
        self.raw: list[int] = []

    def consume(self, packet: bytes) -> tuple[FitorbHistorySample, ...] | None:
        """Consume one packet and return the current non-zero series when available."""
        if len(packet) != 16:
            return None
        index = packet[1]
        if index == 0xFF:
            self.reset()
            return ()
        if index == 0:
            self.expected_count = packet[2]
            self.range_minutes = max(1, packet[3])
            self.raw = []
            return None
        values = packet[3:15] if index == 1 else packet[2:15]
        self.raw.extend(int(value) for value in values)
        samples = [
            FitorbHistorySample(
                metric=self.metric,
                timestamp=self.start_of_day + _minutes(idx * self.range_minutes),
                value=value,
                source_day=self.source_day,
                raw_hex=None,
            )
            for idx, value in enumerate(self.raw)
            if value > 0
        ]
        return tuple(samples)

    def reset(self) -> None:
        """Clear parser state."""
        self.expected_count = 0
        self.range_minutes = 30
        self.raw = []


class BigDataFrameParser:
    """Reassemble variable-length Colmi Big Data frames from chunks."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def consume(self, chunk: bytes) -> list[BigDataFrame]:
        """Consume one BLE chunk and return every complete frame."""
        self._buffer.extend(chunk)
        frames: list[BigDataFrame] = []
        header_len = 6
        while len(self._buffer) >= header_len:
            if self._buffer[0] != BIG_DATA_MAGIC:
                del self._buffer[0]
                continue
            data_id = self._buffer[1]
            data_len = self._buffer[2] | (self._buffer[3] << 8)
            packet_len = header_len + data_len
            if len(self._buffer) < packet_len:
                break
            raw = bytes(self._buffer[:packet_len])
            payload = raw[header_len:]
            frames.append(
                BigDataFrame(
                    data_id=data_id,
                    data_len=data_len,
                    crc16=raw[4] | (raw[5] << 8),
                    payload=payload,
                    raw_hex=raw.hex(),
                )
            )
            del self._buffer[:packet_len]
        return frames
```

- [ ] **Step 5: Run focused protocol tests**

Run: `pytest tests/test_history_protocol.py -v`

Expected: PASS for all tests in `tests/test_history_protocol.py`.

- [ ] **Step 6: Run Ruff on new files**

Run: `ruff check custom_components/fitorb/history_protocol.py tests/test_history_protocol.py`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add custom_components/fitorb/models.py custom_components/fitorb/history_protocol.py tests/test_history_protocol.py
git commit -m "feat: add fitorb history protocol parser"
```

---

### Task 2: Persistent History Ledger

**Files:**
- Create: `custom_components/fitorb/history_store.py`
- Create: `tests/test_history_store.py`
- Modify: `custom_components/fitorb/const.py`

**Interfaces:**
- Produces: `CONF_HISTORY_LOOKBACK_DAYS = "history_lookback_days"`.
- Produces: `CONF_HISTORY_SYNC_INTERVAL = "history_sync_interval"`.
- Produces: `DEFAULT_HISTORY_LOOKBACK_DAYS = 7`.
- Produces: `DEFAULT_HISTORY_SYNC_INTERVAL = timedelta(hours=6)`.
- Produces: `HISTORY_OVERLAP_DAYS = 1`.
- Produces: `FitorbHistoryStore.async_load() -> None`.
- Produces: `FitorbHistoryStore.async_record_result(result: FitorbHistoryResult, synced_at: datetime) -> tuple[FitorbHistorySample, ...]`.
- Produces: `FitorbHistoryStore.last_sync: datetime | None`.
- Produces: `FitorbHistoryStore.last_sample_count: int`.
- Produces: `FitorbHistoryStore.first_sample: datetime | None`.
- Produces: `FitorbHistoryStore.last_sample: datetime | None`.

- [ ] **Step 1: Write failing store tests**

Create `tests/test_history_store.py`:

```python
from __future__ import annotations

from datetime import UTC, date, datetime

from homeassistant.core import HomeAssistant

from custom_components.fitorb.history_store import FitorbHistoryStore
from custom_components.fitorb.models import (
    FitorbHistoryResult,
    FitorbHistorySample,
    HistoryMetric,
)


def _sample(value: int = 72) -> FitorbHistorySample:
    return FitorbHistorySample(
        metric=HistoryMetric.HEART_RATE,
        timestamp=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
        value=value,
        source_day=date(2026, 6, 26),
        raw_hex="1501",
    )


async def test_history_store_deduplicates_samples(hass: HomeAssistant) -> None:
    store = FitorbHistoryStore(hass, "entry-id")
    await store.async_load()
    result = FitorbHistoryResult(samples=(_sample(),), status="success", requested_days=7)

    first = await store.async_record_result(result, datetime(2026, 6, 26, 12, 1, tzinfo=UTC))
    second = await store.async_record_result(result, datetime(2026, 6, 26, 12, 2, tzinfo=UTC))

    assert first == (_sample(),)
    assert second == ()
    assert store.last_sample_count == 1
    assert store.last_sync == datetime(2026, 6, 26, 12, 2, tzinfo=UTC)


async def test_history_store_tracks_first_and_last_sample(hass: HomeAssistant) -> None:
    store = FitorbHistoryStore(hass, "entry-id")
    await store.async_load()
    sample_a = _sample(72)
    sample_b = FitorbHistorySample(
        metric=HistoryMetric.STRESS,
        timestamp=datetime(2026, 6, 26, 13, 0, tzinfo=UTC),
        value=44,
        source_day=date(2026, 6, 26),
    )

    await store.async_record_result(
        FitorbHistoryResult(samples=(sample_b, sample_a), status="success", requested_days=7),
        datetime(2026, 6, 26, 13, 1, tzinfo=UTC),
    )

    assert store.first_sample == sample_a.timestamp
    assert store.last_sample == sample_b.timestamp
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_history_store.py -v`

Expected: FAIL with import error for `custom_components.fitorb.history_store`.

- [ ] **Step 3: Add constants**

Modify `custom_components/fitorb/const.py`:

```python
CONF_HISTORY_LOOKBACK_DAYS = "history_lookback_days"
CONF_HISTORY_SYNC_INTERVAL = "history_sync_interval"

DEFAULT_HISTORY_LOOKBACK_DAYS = 7
DEFAULT_HISTORY_SYNC_INTERVAL = timedelta(hours=6)
HISTORY_OVERLAP_DAYS = 1
```

- [ ] **Step 4: Implement store**

Create `custom_components/fitorb/history_store.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .models import FitorbHistoryResult, FitorbHistorySample, HistoryMetric

_STORE_VERSION = 1


class FitorbHistoryStore:
    """Persist historical sync metadata and dedupe keys for one config entry."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass,
            _STORE_VERSION,
            f"{DOMAIN}_history_{entry_id}",
        )
        self._data: dict[str, Any] = {
            "last_sync": None,
            "last_sample_count": 0,
            "first_sample": None,
            "last_sample": None,
            "samples": {},
        }

    @property
    def last_sync(self) -> datetime | None:
        """Return the last history sync timestamp."""
        return _parse_datetime(self._data.get("last_sync"))

    @property
    def last_sample_count(self) -> int:
        """Return total unique samples recorded in the ledger."""
        return int(self._data.get("last_sample_count") or 0)

    @property
    def first_sample(self) -> datetime | None:
        """Return the earliest unique historical sample timestamp."""
        return _parse_datetime(self._data.get("first_sample"))

    @property
    def last_sample(self) -> datetime | None:
        """Return the latest unique historical sample timestamp."""
        return _parse_datetime(self._data.get("last_sample"))

    async def async_load(self) -> None:
        """Load store data from disk."""
        loaded = await self._store.async_load()
        if loaded is not None:
            self._data.update(loaded)
        self._data.setdefault("samples", {})

    async def async_record_result(
        self,
        result: FitorbHistoryResult,
        synced_at: datetime,
    ) -> tuple[FitorbHistorySample, ...]:
        """Record unique samples from a sync result and persist metadata."""
        samples = self._data.setdefault("samples", {})
        new_samples: list[FitorbHistorySample] = []
        for sample in result.samples:
            key = _sample_key(sample)
            if key in samples:
                continue
            samples[key] = _sample_to_json(sample)
            new_samples.append(sample)
        self._data["last_sync"] = synced_at.astimezone(UTC).isoformat()
        self._data["last_sample_count"] = len(samples)
        all_timestamps = [
            _parse_datetime(item["timestamp"])
            for item in samples.values()
            if item.get("timestamp")
        ]
        valid_timestamps = [stamp for stamp in all_timestamps if stamp is not None]
        self._data["first_sample"] = (
            min(valid_timestamps).isoformat() if valid_timestamps else None
        )
        self._data["last_sample"] = (
            max(valid_timestamps).isoformat() if valid_timestamps else None
        )
        await self._store.async_save(self._data)
        return tuple(new_samples)


def _sample_key(sample: FitorbHistorySample) -> str:
    return "|".join(
        [
            sample.metric.value,
            sample.timestamp.astimezone(UTC).isoformat(),
            str(sample.value),
        ]
    )


def _sample_to_json(sample: FitorbHistorySample) -> dict[str, Any]:
    return {
        "metric": sample.metric.value,
        "timestamp": sample.timestamp.astimezone(UTC).isoformat(),
        "value": sample.value,
        "source_day": sample.source_day.isoformat(),
        "raw_hex": sample.raw_hex,
    }


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
```

- [ ] **Step 5: Run focused store tests**

Run: `pytest tests/test_history_store.py -v`

Expected: PASS.

- [ ] **Step 6: Run Ruff on store files**

Run: `ruff check custom_components/fitorb/history_store.py tests/test_history_store.py`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add custom_components/fitorb/const.py custom_components/fitorb/history_store.py tests/test_history_store.py
git commit -m "feat: add fitorb history ledger"
```

---

### Task 3: BLE History Read Path

**Files:**
- Modify: `custom_components/fitorb/bluetooth.py`
- Modify: `tests/test_coordinator.py`

**Interfaces:**
- Produces: `FitorbHistoryRequest(days: tuple[date, ...], day_offsets: tuple[int, ...])` in `models.py`.
- Produces: `FitorbBleClient.async_read_current_data_with_history(base: FitorbData, *, include_health: bool = True, history_request: FitorbHistoryRequest | None = None) -> FitorbReadResult`.
- Keeps: `FitorbBleClient.async_read_current_data(...) -> FitorbData` as a compatibility wrapper.

- [ ] **Step 1: Add request model**

Modify `custom_components/fitorb/models.py`:

```python
@dataclass(frozen=True, slots=True)
class FitorbHistoryRequest:
    """History ranges requested during one BLE session."""

    days: tuple[date, ...]
    day_offsets: tuple[int, ...]
```

- [ ] **Step 2: Write failing BLE history tests**

Append to `tests/test_coordinator.py`:

```python
from datetime import date

from custom_components.fitorb.models import FitorbHistoryRequest, FitorbReadResult


async def test_ble_client_reads_heart_rate_history_after_live_values() -> None:
    class FakeBleakClient:
        def __init__(self) -> None:
            self.handler = None
            self.commands: list[bytes] = []

        async def start_notify(self, _uuid, handler) -> None:
            self.handler = handler

        async def write_gatt_char(self, _uuid, payload: bytes) -> None:
            self.commands.append(payload)
            assert self.handler is not None
            if payload[0] == 0x03:
                self.handler(1, bytearray(_battery_notification(level=82)))
            elif payload[0] == 0x15:
                self.handler(1, bytearray(bytes([21, 0, 2, 5, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 28])))
                self.handler(1, bytearray(bytes([21, 1, 0, 193, 61, 106, 72, 0, 0, 0, 0, 0, 75, 0, 0, 211])))

        async def stop_notify(self, _uuid) -> None:
            return None

        async def disconnect(self) -> None:
            return None

    fake_client = FakeBleakClient()
    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    client = FitorbBleClient(hass, "AA:BB:CC:DD:EE:FF", response_timeout=0.05)

    with (
        patch(
            "custom_components.fitorb.bluetooth.bluetooth.async_ble_device_from_address",
            return_value=object(),
        ),
        patch(
            "custom_components.fitorb.bluetooth.establish_connection",
            AsyncMock(return_value=fake_client),
        ),
    ):
        result = await client.async_read_current_data_with_history(
            FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring"),
            include_health=False,
            history_request=FitorbHistoryRequest(
                days=(date(2026, 6, 26),),
                day_offsets=(0,),
            ),
        )

    assert isinstance(result, FitorbReadResult)
    assert result.data.battery_level == 82
    assert result.history is not None
    assert result.history.status == "success"
    assert [sample.value for sample in result.history.samples] == [72, 75]
    assert any(command[0] == 0x15 for command in fake_client.commands)


async def test_ble_client_history_timeout_keeps_live_result() -> None:
    class FakeBleakClient:
        def __init__(self) -> None:
            self.handler = None

        async def start_notify(self, _uuid, handler) -> None:
            self.handler = handler

        async def write_gatt_char(self, _uuid, payload: bytes) -> None:
            assert self.handler is not None
            if payload[0] == 0x03:
                self.handler(1, bytearray(_battery_notification(level=82)))

        async def stop_notify(self, _uuid) -> None:
            return None

        async def disconnect(self) -> None:
            return None

    hass = SimpleNamespace(loop=asyncio.get_running_loop())
    client = FitorbBleClient(hass, "AA:BB:CC:DD:EE:FF", response_timeout=0.05)

    with (
        patch(
            "custom_components.fitorb.bluetooth.bluetooth.async_ble_device_from_address",
            return_value=object(),
        ),
        patch(
            "custom_components.fitorb.bluetooth.establish_connection",
            AsyncMock(return_value=FakeBleakClient()),
        ),
    ):
        result = await client.async_read_current_data_with_history(
            FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring"),
            include_health=False,
            history_request=FitorbHistoryRequest(
                days=(date(2026, 6, 26),),
                day_offsets=(0,),
            ),
        )

    assert result.data.battery_level == 82
    assert result.history is not None
    assert result.history.status == "partial"
    assert result.history.samples == ()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_coordinator.py::test_ble_client_reads_heart_rate_history_after_live_values tests/test_coordinator.py::test_ble_client_history_timeout_keeps_live_result -v`

Expected: FAIL because `FitorbHistoryRequest` and `async_read_current_data_with_history` do not exist yet.

- [ ] **Step 4: Add BLE read wrapper**

Modify `custom_components/fitorb/bluetooth.py` imports:

```python
from datetime import UTC, datetime

from .history_protocol import (
    build_heart_rate_history_command,
    parse_heart_rate_history_packets,
)
from .models import (
    FitorbData,
    FitorbHistoryRequest,
    FitorbHistoryResult,
    FitorbReadResult,
    NotificationKind,
)
```

Change `async_read_current_data` into a compatibility wrapper:

```python
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
```

Add `async_read_current_data_with_history` by moving the existing connection body into it and returning `FitorbReadResult(data=snapshot, history=history_result)`. After health reads and before `return`, call:

```python
            history_result = None
            if history_request is not None:
                history_result = await self._read_history(queue, client, history_request)
            return FitorbReadResult(data=snapshot, history=history_result)
```

- [ ] **Step 5: Add heart-rate history read helper**

Add this method to `FitorbBleClient`:

```python
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
        status = "success"
        for target_day in request.days:
            packets: list[bytes] = []
            try:
                await client.write_gatt_char(
                    CMD_WRITE_CHAR_UUID,
                    build_heart_rate_history_command(target_day),
                )
                packets = await self._drain_history_packets(
                    queue,
                    expected_command=0x15,
                )
            except Exception as err:
                _LOGGER.debug(
                    "Unable to read Fitorb heart_rate history for %s: %s",
                    target_day.isoformat(),
                    err,
                )
                status = "partial"
                continue
            samples.extend(parse_heart_rate_history_packets(packets))
        ordered = tuple(sorted(samples, key=lambda sample: sample.timestamp))
        return FitorbHistoryResult(
            samples=ordered,
            status=status,
            requested_days=len(request.days),
            first_sample=ordered[0].timestamp if ordered else None,
            last_sample=ordered[-1].timestamp if ordered else None,
            unknown_packets=unknown_packets,
            malformed_packets=malformed_packets,
        )
```

Add this drain helper:

```python
    async def _drain_history_packets(
        self,
        queue: asyncio.Queue[bytes],
        *,
        expected_command: int,
    ) -> list[bytes]:
        """Drain history packets until a parser-visible end or timeout."""
        packets: list[bytes] = []
        end_time = self.hass.loop.time() + self.response_timeout
        while self.hass.loop.time() < end_time:
            timeout = max(0.1, end_time - self.hass.loop.time())
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=timeout)
            except TimeoutError:
                break
            if len(payload) != 16:
                _LOGGER.debug("Malformed Fitorb history notification: %s", payload.hex())
                continue
            if payload[0] != expected_command:
                _LOGGER.debug("Unknown Fitorb history notification: %s", payload.hex())
                continue
            packets.append(payload)
            if payload[1] == 0xFF:
                break
            if payload[1] > 0 and packets and packets[0][1] == 0:
                expected_packets = packets[0][2]
                if expected_packets and payload[1] >= expected_packets - 1:
                    break
        if not packets:
            raise FitorbResponseTimeout("Timed out waiting for Fitorb history response")
        return packets
```

- [ ] **Step 6: Run focused BLE tests**

Run: `pytest tests/test_coordinator.py::test_ble_client_reads_heart_rate_history_after_live_values tests/test_coordinator.py::test_ble_client_history_timeout_keeps_live_result -v`

Expected: PASS.

- [ ] **Step 7: Run current BLE regression tests**

Run: `pytest tests/test_coordinator.py -v`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add custom_components/fitorb/models.py custom_components/fitorb/bluetooth.py tests/test_coordinator.py
git commit -m "feat: read fitorb heart rate history"
```

---

### Task 4: Coordinator Due Logic And Options Flow

**Files:**
- Modify: `custom_components/fitorb/config_flow.py`
- Modify: `custom_components/fitorb/coordinator.py`
- Modify: `custom_components/fitorb/__init__.py`
- Modify: `tests/test_config_flow.py`
- Modify: `tests/test_coordinator.py`

**Interfaces:**
- Consumes: `FitorbHistoryRequest`, `FitorbReadResult`, `FitorbHistoryStore`.
- Produces: config options `history_lookback_days=7` and `history_sync_interval=360`.
- Produces: `FitorbDataUpdateCoordinator.history_store`.
- Produces: `_history_sync_is_due(now: datetime) -> bool`.
- Produces: `_build_history_request(now: datetime) -> FitorbHistoryRequest`.

- [ ] **Step 1: Write failing config-flow tests**

Update option assertions in `tests/test_config_flow.py` so both create-entry tests expect:

```python
    assert result["options"] == {
        CONF_SCAN_INTERVAL: 5,
        CONF_HEALTH_POLL_INTERVAL: 15,
        CONF_HISTORY_LOOKBACK_DAYS: 7,
        CONF_HISTORY_SYNC_INTERVAL: 360,
    }
```

Add imports:

```python
    CONF_HISTORY_LOOKBACK_DAYS,
    CONF_HISTORY_SYNC_INTERVAL,
```

Append:

```python
async def test_options_flow_updates_history_settings(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Ring",
        data={CONF_ADDRESS: "AA:BB:CC:DD:EE:FF", CONF_NAME: "Ring"},
        options={
            CONF_SCAN_INTERVAL: 5,
            CONF_HEALTH_POLL_INTERVAL: 15,
            CONF_HISTORY_LOOKBACK_DAYS: 7,
            CONF_HISTORY_SYNC_INTERVAL: 360,
        },
    )
    entry.add_to_hass(hass)

    flow = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        user_input={
            CONF_SCAN_INTERVAL: 5,
            CONF_HEALTH_POLL_INTERVAL: 15,
            CONF_HISTORY_LOOKBACK_DAYS: 3,
            CONF_HISTORY_SYNC_INTERVAL: 120,
        },
    )

    assert result["type"] is config_entries.FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HISTORY_LOOKBACK_DAYS] == 3
    assert result["data"][CONF_HISTORY_SYNC_INTERVAL] == 120
```

- [ ] **Step 2: Write failing coordinator tests**

Update the existing datetime import in `tests/test_coordinator.py`:

```python
from datetime import UTC, date, datetime
```

Update the existing model import in `tests/test_coordinator.py`:

```python
from custom_components.fitorb.models import (
    FitorbData,
    FitorbHistoryRequest,
    FitorbHistoryResult,
    FitorbHistorySample,
    FitorbReadResult,
    HistoryMetric,
    NotificationKind,
)
```

Update `FakeRingClient` in `tests/test_coordinator.py`:

```python
    def __init__(
        self,
        data: FitorbData | None = None,
        err: Exception | None = None,
        read_result: FitorbReadResult | None = None,
    ) -> None:
        self.data = data
        self.err = err
        self.read_result = read_result
        self.calls = 0
        self.include_health_calls: list[bool] = []
        self.history_requests: list[FitorbHistoryRequest | None] = []

    async def async_read_current_data_with_history(
        self,
        base: FitorbData,
        *,
        include_health: bool = True,
        history_request: FitorbHistoryRequest | None = None,
    ) -> FitorbReadResult:
        self.calls += 1
        self.include_health_calls.append(include_health)
        self.history_requests.append(history_request)
        if self.err is not None:
            raise self.err
        if self.read_result is not None:
            return self.read_result
        assert self.data is not None
        return FitorbReadResult(data=self.data)

    async def async_read_current_data(
        self,
        base: FitorbData,
        *,
        include_health: bool = True,
    ) -> FitorbData:
        return (
            await self.async_read_current_data_with_history(
                base,
                include_health=include_health,
                history_request=None,
            )
        ).data
```

Add a fake store:

```python
class FakeHistoryStore:
    def __init__(self) -> None:
        self.last_sync = None
        self.last_sample_count = 0
        self.first_sample = None
        self.last_sample = None
        self.recorded_results: list[FitorbHistoryResult] = []

    async def async_load(self) -> None:
        return None

    async def async_record_result(
        self,
        result: FitorbHistoryResult,
        synced_at: datetime,
    ) -> tuple[FitorbHistorySample, ...]:
        self.last_sync = synced_at
        self.last_sample_count += len(result.samples)
        self.first_sample = result.first_sample
        self.last_sample = result.last_sample
        self.recorded_results.append(result)
        return result.samples
```

Append:

```python
async def test_coordinator_requests_history_when_due(
    hass: HomeAssistant,
    entry: MockConfigEntry,
) -> None:
    sample = FitorbHistorySample(
        metric=HistoryMetric.HEART_RATE,
        timestamp=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
        value=72,
        source_day=date(2026, 6, 26),
    )
    history = FitorbHistoryResult(
        samples=(sample,),
        status="success",
        requested_days=7,
        first_sample=sample.timestamp,
        last_sample=sample.timestamp,
    )
    client = FakeRingClient(
        read_result=FitorbReadResult(
            data=FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring", available=True),
            history=history,
        )
    )
    store = FakeHistoryStore()
    coordinator = FitorbDataUpdateCoordinator(hass, entry, client, history_store=store)

    result = await coordinator._async_update_data()

    assert client.history_requests[0] is not None
    assert client.history_requests[0].day_offsets[0] == 0
    assert result.last_history_status == "success"
    assert result.last_history_sample_count == 1


async def test_coordinator_skips_history_when_not_due(
    hass: HomeAssistant,
    entry: MockConfigEntry,
) -> None:
    client = FakeRingClient(
        data=FitorbData(address="AA:BB:CC:DD:EE:FF", name="Ring", available=True)
    )
    store = FakeHistoryStore()
    store.last_sync = datetime.now(UTC)
    coordinator = FitorbDataUpdateCoordinator(hass, entry, client, history_store=store)

    await coordinator._async_update_data()

    assert client.history_requests == [None]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_config_flow.py tests/test_coordinator.py::test_coordinator_requests_history_when_due tests/test_coordinator.py::test_coordinator_skips_history_when_not_due -v`

Expected: FAIL because history options and coordinator store wiring do not exist.

- [ ] **Step 4: Add default options and options flow**

Modify `_default_options()` in `custom_components/fitorb/config_flow.py`:

```python
    return {
        CONF_SCAN_INTERVAL: int(DEFAULT_SUMMARY_POLL_INTERVAL.total_seconds() / 60),
        CONF_HEALTH_POLL_INTERVAL: int(
            DEFAULT_HEALTH_POLL_INTERVAL.total_seconds() / 60
        ),
        CONF_HISTORY_LOOKBACK_DAYS: DEFAULT_HISTORY_LOOKBACK_DAYS,
        CONF_HISTORY_SYNC_INTERVAL: int(
            DEFAULT_HISTORY_SYNC_INTERVAL.total_seconds() / 60
        ),
    }
```

Add imports for the new constants and implement:

```python
    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return FitorbOptionsFlow(config_entry)


class FitorbOptionsFlow(config_entries.OptionsFlow):
    """Handle Fitorb options."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Manage Fitorb polling options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = {**_default_options(), **self.entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=options[CONF_SCAN_INTERVAL],
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
                    vol.Required(
                        CONF_HEALTH_POLL_INTERVAL,
                        default=options[CONF_HEALTH_POLL_INTERVAL],
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=120)),
                    vol.Required(
                        CONF_HISTORY_LOOKBACK_DAYS,
                        default=options[CONF_HISTORY_LOOKBACK_DAYS],
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=14)),
                    vol.Required(
                        CONF_HISTORY_SYNC_INTERVAL,
                        default=options[CONF_HISTORY_SYNC_INTERVAL],
                    ): vol.All(vol.Coerce(int), vol.Range(min=30, max=1440)),
                }
            ),
        )
```

- [ ] **Step 5: Wire coordinator history store**

Modify `FitorbDataUpdateCoordinator.__init__` signature:

```python
        history_store: FitorbHistoryStore | None = None,
```

Set:

```python
        self.history_store = history_store or FitorbHistoryStore(hass, entry.entry_id)
        self.history_lookback_days = int(
            entry.options.get(CONF_HISTORY_LOOKBACK_DAYS, DEFAULT_HISTORY_LOOKBACK_DAYS)
        )
        self.history_sync_interval = timedelta(
            minutes=int(
                entry.options.get(
                    CONF_HISTORY_SYNC_INTERVAL,
                    DEFAULT_HISTORY_SYNC_INTERVAL.total_seconds() / 60,
                )
            )
        )
```

In `custom_components/fitorb/__init__.py`, after creating the coordinator and before first refresh:

```python
    await coordinator.history_store.async_load()
```

Update `test_setup_entry_keeps_entry_loaded_on_first_refresh_failure` so the fake coordinator exposes the loaded store:

```python
    fake_coordinator = SimpleNamespace(
        base_data=base_data,
        history_store=SimpleNamespace(async_load=AsyncMock()),
        async_set_updated_data=AsyncMock(),
        async_config_entry_first_refresh=AsyncMock(
            side_effect=ConfigEntryNotReady("ring offline")
        ),
    )
```

- [ ] **Step 6: Update coordinator polling**

In `_async_update_data`, replace the client call with:

```python
            now = datetime.now(UTC)
            history_request = (
                self._build_history_request(now)
                if self._history_sync_is_due(now)
                else None
            )
            read_result = await self.client.async_read_current_data_with_history(
                base,
                include_health=include_health,
                history_request=history_request,
            )
            data = read_result.data
            history = read_result.history
            if history is not None:
                await self.history_store.async_record_result(history, now)
                data = data.with_values(
                    last_history_sync=now,
                    last_history_sample_count=self.history_store.last_sample_count,
                    last_history_status=history.status,
                    last_history_first_sample=self.history_store.first_sample,
                    last_history_last_sample=self.history_store.last_sample,
                    history_unknown_packets=history.unknown_packets,
                    history_malformed_packets=history.malformed_packets,
                )
```

Use the existing `updated_at` logic after this block and avoid a second `datetime.now(UTC)` if practical.

Add:

```python
    def _history_sync_is_due(self, now: datetime) -> bool:
        """Return whether history sync should run on this update."""
        if self.history_store.last_sync is None:
            return True
        return now - self.history_store.last_sync >= self.history_sync_interval

    def _build_history_request(self, now: datetime) -> FitorbHistoryRequest:
        """Build history request days with a fixed overlap."""
        lookback = max(1, self.history_lookback_days)
        offsets = tuple(range(0, lookback + HISTORY_OVERLAP_DAYS))
        today = now.date()
        days = tuple(today - timedelta(days=offset) for offset in offsets)
        return FitorbHistoryRequest(days=days, day_offsets=offsets)
```

- [ ] **Step 7: Run focused tests**

Run: `pytest tests/test_config_flow.py tests/test_coordinator.py -v`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add custom_components/fitorb/config_flow.py custom_components/fitorb/coordinator.py custom_components/fitorb/__init__.py tests/test_config_flow.py tests/test_coordinator.py
git commit -m "feat: schedule fitorb history sync"
```

---

### Task 5: History Diagnostic Sensors, Diagnostics, And Translations

**Files:**
- Modify: `custom_components/fitorb/sensor.py`
- Modify: `custom_components/fitorb/diagnostics.py`
- Modify: `custom_components/fitorb/strings.json`
- Modify: `custom_components/fitorb/translations/de.json`
- Modify: `custom_components/fitorb/translations/en.json`
- Modify: `tests/test_sensor.py`
- Modify: `tests/test_diagnostics.py`

**Interfaces:**
- Consumes: history fields on `FitorbData`.
- Produces diagnostic sensors:
  - `last_history_sync`
  - `last_history_sample_count`
  - `last_history_status`
  - `last_history_first_sample`
  - `last_history_last_sample`

- [ ] **Step 1: Write failing sensor tests**

Update `_sample_data()` in `tests/test_sensor.py` with:

```python
        last_history_sync=datetime(2026, 6, 26, 3, 0, tzinfo=UTC),
        last_history_sample_count=24,
        last_history_status="success",
        last_history_first_sample=datetime(2026, 6, 25, 0, 0, tzinfo=UTC),
        last_history_last_sample=datetime(2026, 6, 26, 0, 0, tzinfo=UTC),
```

Extend the `test_all_sensor_descriptors_map_values_and_metadata` parametrization:

```python
        (
            "last_history_sync",
            datetime(2026, 6, 26, 3, 0, tzinfo=UTC),
            "last_history_sync",
            None,
            "timestamp",
        ),
        ("last_history_sample_count", 24, "last_history_sample_count", None, None),
        ("last_history_status", "success", "last_history_status", None, None),
        (
            "last_history_first_sample",
            datetime(2026, 6, 25, 0, 0, tzinfo=UTC),
            "last_history_first_sample",
            None,
            "timestamp",
        ),
        (
            "last_history_last_sample",
            datetime(2026, 6, 26, 0, 0, tzinfo=UTC),
            "last_history_last_sample",
            None,
            "timestamp",
        ),
```

- [ ] **Step 2: Write failing diagnostics test**

Extend `tests/test_diagnostics.py` expected diagnostics:

```python
    assert diagnostics["history"] == {
        "last_sync": "2026-06-26T03:00:00+00:00",
        "sample_count": 24,
        "status": "success",
        "first_sample": "2026-06-25T00:00:00+00:00",
        "last_sample": "2026-06-26T00:00:00+00:00",
        "unknown_packets": 2,
        "malformed_packets": 1,
    }
```

Use `FitorbData` values matching those assertions.

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_sensor.py tests/test_diagnostics.py -v`

Expected: FAIL because descriptors and diagnostics keys do not exist.

- [ ] **Step 4: Add sensor descriptors**

Add descriptors to `SENSOR_DESCRIPTIONS` in `custom_components/fitorb/sensor.py`:

```python
    "last_history_sync": FitorbSensorDescription(
        key="last_history_sync",
        translation_key="last_history_sync",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.last_history_sync,
    ),
    "last_history_sample_count": FitorbSensorDescription(
        key="last_history_sample_count",
        translation_key="last_history_sample_count",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.last_history_sample_count,
    ),
    "last_history_status": FitorbSensorDescription(
        key="last_history_status",
        translation_key="last_history_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.last_history_status,
    ),
    "last_history_first_sample": FitorbSensorDescription(
        key="last_history_first_sample",
        translation_key="last_history_first_sample",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.last_history_first_sample,
    ),
    "last_history_last_sample": FitorbSensorDescription(
        key="last_history_last_sample",
        translation_key="last_history_last_sample",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.last_history_last_sample,
    ),
```

- [ ] **Step 5: Add diagnostics**

In `custom_components/fitorb/diagnostics.py`, add helper:

```python
def _iso_or_none(value) -> str | None:
    return value.isoformat() if value else None
```

Add to returned diagnostics:

```python
        "history": {
            "last_sync": _iso_or_none(data.last_history_sync) if data else None,
            "sample_count": data.last_history_sample_count if data else None,
            "status": data.last_history_status if data else None,
            "first_sample": _iso_or_none(data.last_history_first_sample)
            if data
            else None,
            "last_sample": _iso_or_none(data.last_history_last_sample)
            if data
            else None,
            "unknown_packets": data.history_unknown_packets if data else 0,
            "malformed_packets": data.history_malformed_packets if data else 0,
        },
```

- [ ] **Step 6: Add translations**

Add these sensor translation keys to `strings.json`, `translations/en.json`, and `translations/de.json`.

English:

```json
"last_history_sync": { "name": "Last history sync" },
"last_history_sample_count": { "name": "History sample count" },
"last_history_status": { "name": "History sync status" },
"last_history_first_sample": { "name": "First history sample" },
"last_history_last_sample": { "name": "Last history sample" }
```

German:

```json
"last_history_sync": { "name": "Letzter History-Sync" },
"last_history_sample_count": { "name": "History-Samples" },
"last_history_status": { "name": "History-Sync-Status" },
"last_history_first_sample": { "name": "Erstes History-Sample" },
"last_history_last_sample": { "name": "Letztes History-Sample" }
```

Add option labels:

English:

```json
"history_lookback_days": "History lookback days",
"history_sync_interval": "History sync interval"
```

German:

```json
"history_lookback_days": "History-Zeitraum in Tagen",
"history_sync_interval": "History-Sync-Intervall"
```

- [ ] **Step 7: Run focused tests**

Run: `pytest tests/test_sensor.py tests/test_diagnostics.py -v`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add custom_components/fitorb/sensor.py custom_components/fitorb/diagnostics.py custom_components/fitorb/strings.json custom_components/fitorb/translations/de.json custom_components/fitorb/translations/en.json tests/test_sensor.py tests/test_diagnostics.py
git commit -m "feat: expose fitorb history diagnostics"
```

---

### Task 6: Documentation, Version, And Validation Notes

**Files:**
- Modify: `README.md`
- Modify: `custom_components/fitorb/manifest.json`
- Modify: `tests/test_manifest.py`

**Interfaces:**
- Produces: user-facing notes for Bluetooth range, cache uncertainty, QRing/phone limitations, and debug validation.
- Produces: manifest version `0.2.0`.

- [ ] **Step 1: Write failing manifest version test**

Add to `tests/test_manifest.py`:

```python
def test_manifest_version_is_history_release() -> None:
    manifest = json.loads(
        (ROOT / "custom_components" / "fitorb" / "manifest.json").read_text()
    )

    assert manifest["version"] == "0.2.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_manifest.py::test_manifest_version_is_history_release -v`

Expected: FAIL because manifest version is still `0.1.3` or another Version 1 value.

- [ ] **Step 3: Update manifest**

Set in `custom_components/fitorb/manifest.json`:

```json
"version": "0.2.0"
```

- [ ] **Step 4: Update README scope**

Replace the Version 1 history sentence with:

```markdown
Version 2 adds an experimental direct BLE history sync. It reads cached ring data
when the ring returns to Home Assistant Bluetooth range, deduplicates samples
locally, and exposes diagnostics so the real retention window can be measured on
your ring firmware.
```

Add a new section:

```markdown
## Historical Sync

Historical sync uses the same direct Bluetooth path as the live sensors. The ring
must come back into range of the Home Assistant Bluetooth adapter or an active
GATT-capable proxy before cached samples can be recovered. The phone app and the
Home Assistant mobile app do not relay these BLE GATT reads.

The default lookback is 7 days with a 1 day overlap. The exact retention window is
firmware-dependent and not guaranteed by the public Colmi references. Use the
diagnostic sensors `Last history sync`, `History sample count`, `First history
sample`, and `Last history sample` to see what the ring actually returned.

The first history release stores and deduplicates parsed samples for validation.
It does not write old Home Assistant recorder state rows. Long-term statistics
publishing will be added after the packet timestamps and units are confirmed with
real hardware logs.
```

Extend debug logging with:

```markdown
History debug logs may include raw historical BLE packets. These are useful when
checking whether QRing sync changes what Home Assistant can later read.
```

- [ ] **Step 5: Run docs and manifest tests**

Run: `pytest tests/test_manifest.py -v`

Expected: PASS.

- [ ] **Step 6: Run full test suite**

Run: `pytest -v`

Expected: PASS.

- [ ] **Step 7: Run Ruff**

Run: `ruff check custom_components tests`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add README.md custom_components/fitorb/manifest.json tests/test_manifest.py
git commit -m "docs: document fitorb history sync"
```

---

## Manual Validation Checklist

- [ ] Install the branch in Home Assistant.
- [ ] Restart Home Assistant.
- [ ] Reload the Fitorb integration.
- [ ] Keep the ring in Bluetooth range for one update cycle.
- [ ] Confirm live sensors still show current battery, activity, and health values.
- [ ] Confirm diagnostic sensors show `Last history sync` and `History sync status`.
- [ ] Leave the ring away from the HA Bluetooth dongle for 1 day.
- [ ] Bring the ring back into range and wait for a history sync.
- [ ] Record diagnostic values: sample count, first sample, last sample.
- [ ] Repeat with 2, 3, and 7 day absences if practical.
- [ ] Compare heart-rate history values with QRing for the same day.
- [ ] Test once where QRing syncs first, then Home Assistant syncs, and record whether sample count changes.
- [ ] Save debug logs containing unknown history packets for parser refinement.

---

## Full Verification

Run:

```bash
pytest -v
ruff check custom_components tests
```

Expected:

- `pytest` exits with code 0.
- `ruff` exits with code 0.
- `git status --short` shows only intentional files before each commit.

---

## Future Statistics Publishing Gate

After manual validation confirms timestamps and units, add a separate plan for long-term statistics publishing. That plan must use Home Assistant-supported recorder statistics APIs and must not insert rows directly into recorder state tables. Candidate metrics for statistics are `heart_rate`, `spo2`, `stress`, `steps`, `calories`, and `distance`, but each metric needs confirmed units, state class semantics, and aggregation behavior before publishing.

---

## Self-Review

- Spec coverage: This plan covers direct BLE history reads, parser separation, lookback and overlap, persistent dedupe, diagnostic sensors, unknown/malformed packet handling, partial failure behavior, README notes, and real hardware validation.
- Deliberate gap: Long-term statistics publishing is not implemented in this plan because the approved design requires packet semantics to be confirmed on real hardware first.
- Type consistency: `FitorbHistoryRequest`, `FitorbReadResult`, `FitorbHistoryResult`, `FitorbHistorySample`, and `HistoryMetric` are introduced before consumers use them.
- Placeholder scan: No unresolved implementation placeholders are intended in this plan.
