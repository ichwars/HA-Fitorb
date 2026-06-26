from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo

from .models import FitorbHistorySample, FitorbSleepSummary, HistoryMetric
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


@dataclass(frozen=True, slots=True)
class SleepHistoryParseResult:
    """Parsed sleep history samples and latest summary."""

    samples: tuple[FitorbHistorySample, ...]
    summary: FitorbSleepSummary | None


_SLEEP_STAGE_LABELS = {
    2: "light",
    3: "deep",
    4: "rem",
    5: "awake",
}


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


def parse_sleep_history_payload(
    payload: bytes,
    *,
    today: date | None = None,
    tz: tzinfo = UTC,
) -> SleepHistoryParseResult:
    """Parse Colmi Big Data sleep payload 0x27 into stage samples and summary."""
    if not payload:
        return SleepHistoryParseResult(samples=(), summary=None)

    today = today or datetime.now(tz).date()
    sleep_days = payload[0]
    offset = 1
    samples: list[FitorbHistorySample] = []
    summaries: list[tuple[int, FitorbSleepSummary]] = []

    for _ in range(sleep_days):
        if offset + 2 > len(payload):
            break

        days_ago = payload[offset]
        day_payload_len = payload[offset + 1]
        day_payload_start = offset + 2
        day_payload_end = day_payload_start + day_payload_len
        if day_payload_len < 4 or day_payload_end > len(payload):
            break

        source_day = today - timedelta(days=days_ago)
        sleep_start = int.from_bytes(
            payload[offset + 2 : offset + 4],
            "little",
            signed=True,
        )
        sleep_end = int.from_bytes(
            payload[offset + 4 : offset + 6],
            "little",
            signed=True,
        )
        duration_minutes = _sleep_duration_minutes(sleep_start, sleep_end)
        start = datetime.combine(source_day, time.min, tzinfo=tz) + _minutes(
            sleep_start
        )
        end = start + _minutes(duration_minutes)

        stage_minutes = {"awake": 0, "light": 0, "deep": 0, "rem": 0}
        cursor = 0
        period_offset = day_payload_start + 4
        while period_offset + 2 <= day_payload_end:
            stage_raw = payload[period_offset]
            minutes = payload[period_offset + 1]
            period_offset += 2
            stage = _SLEEP_STAGE_LABELS.get(stage_raw)
            if stage is None:
                cursor += minutes
                continue

            stage_minutes[stage] += minutes
            samples.append(
                FitorbHistorySample(
                    metric=HistoryMetric.SLEEP_STAGE,
                    timestamp=start + _minutes(cursor),
                    value=stage,
                    source_day=source_day,
                    raw_hex=bytes([stage_raw, minutes]).hex(),
                )
            )
            cursor += minutes

        awake_minutes = stage_minutes["awake"]
        summaries.append(
            (
                days_ago,
                FitorbSleepSummary(
                    source_day=source_day,
                    start=start,
                    end=end,
                    duration_minutes=duration_minutes,
                    asleep_minutes=max(0, duration_minutes - awake_minutes),
                    awake_minutes=awake_minutes,
                    light_minutes=stage_minutes["light"],
                    deep_minutes=stage_minutes["deep"],
                    rem_minutes=stage_minutes["rem"],
                ),
            )
        )
        offset = day_payload_end

    summary = min(summaries, key=lambda item: item[0])[1] if summaries else None
    return SleepHistoryParseResult(samples=tuple(samples), summary=summary)


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
    return samples or parser.finish_partial()


class HeartRateHistoryParser:
    """Accumulate command 0x15 packets into heart-rate history samples."""

    def __init__(self) -> None:
        self._reset()

    def consume(self, packet: bytes) -> tuple[FitorbHistorySample, ...] | None:
        """Consume one packet and return samples when the response is complete."""
        if len(packet) != 16 or packet[0] != COMMAND_HISTORY_HEART_RATE:
            return None

        subtype = packet[1]
        if subtype == 0xFF:
            self._reset()
            return ()
        if subtype == 0:
            self._expected_packets = packet[2]
            self._range_minutes = max(1, packet[3])
            self._raw = []
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

    def finish_partial(self) -> tuple[FitorbHistorySample, ...]:
        """Return samples from packets received before a transfer completed."""
        return self._samples()

    def _append_values(self, values: bytes) -> None:
        self._raw.extend(int(value) for value in values)

    def _samples(self) -> tuple[FitorbHistorySample, ...]:
        if self._timestamp is None:
            self._reset()
            return ()

        source_day = self._timestamp.date()
        samples = tuple(
            FitorbHistorySample(
                metric=HistoryMetric.HEART_RATE,
                timestamp=self._timestamp + _minutes(index * self._range_minutes),
                value=value,
                source_day=source_day,
                raw_hex=None,
            )
            for index, value in enumerate(self._raw)
            if value > 0
        )
        self._reset()
        return samples

    def _reset(self) -> None:
        self._expected_packets = 0
        self._range_minutes = 5
        self._timestamp: datetime | None = None
        self._raw: list[int] = []


def _minutes(value: int) -> timedelta:
    return timedelta(minutes=value)


def _sleep_duration_minutes(start: int, end: int) -> int:
    if end <= start:
        return (24 * 60 - start) + end
    return end - start


class SplitSeriesHistoryParser:
    """Parse split-array series packets used by stress history."""

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
        if len(packet) not in (15, 16):
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

        if index == 1:
            values = packet[3:14] if len(packet) == 15 else packet[3:15]
        else:
            values = packet[2:14] if len(packet) == 15 else packet[2:15]
        self.raw.extend(int(value) for value in values)
        return tuple(
            FitorbHistorySample(
                metric=self.metric,
                timestamp=self.start_of_day + _minutes(idx * self.range_minutes),
                value=value,
                source_day=self.source_day,
                raw_hex=None,
            )
            for idx, value in enumerate(self.raw)
            if value > 0
        )

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
