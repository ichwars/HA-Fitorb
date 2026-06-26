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
    parse_sleep_history_payload,
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

    assert (
        parser.consume(bytes([55, 0, 24, 30, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 92]))
        is None
    )
    samples = parser.consume(
        bytes([55, 1, 24, 61, 0, 58, 55, 0, 60, 68, 56, 67, 62, 69, 224])
    )

    assert samples is not None
    assert [(sample.timestamp.hour, sample.value) for sample in samples] == [
        (0, 61),
        (1, 58),
        (1, 55),
        (2, 60),
        (3, 68),
        (3, 56),
        (4, 67),
        (4, 62),
        (5, 69),
    ]
    assert len(samples) == 9
    assert all(sample.value != 224 for sample in samples)
    assert samples[0].timestamp == datetime(2026, 6, 26, tzinfo=UTC)
    assert samples[1].timestamp == datetime(2026, 6, 26, 1, 0, tzinfo=UTC)
    assert samples[-1].timestamp == datetime(2026, 6, 26, 5, 0, tzinfo=UTC)


def test_big_data_frame_parser_reassembles_chunked_sleep_response() -> None:
    parser = BigDataFrameParser()
    payload = bytes([2, 1, 8, 100, 5, 200, 1, 2, 30, 3, 18])
    frame = bytes([0xBC, 0x27, len(payload), 0, 0x79, 0xED]) + payload

    assert parser.consume(frame[:4]) == []
    frames = parser.consume(frame[4:])

    assert len(frames) == 1
    assert frames[0].data_id == 0x27
    assert frames[0].payload == payload


def test_parse_sleep_history_payload_decodes_stage_summary() -> None:
    payload = bytes(
        [
            1,
            0,
            16,
            0x64,
            0x05,
            0x34,
            0x01,
            2,
            60,
            3,
            45,
            4,
            48,
            2,
            120,
            5,
            5,
            3,
            90,
        ]
    )

    result = parse_sleep_history_payload(payload, today=date(2026, 6, 26))

    assert result.summary is not None
    assert result.summary.start == datetime(2026, 6, 26, 23, 0, tzinfo=UTC)
    assert result.summary.end == datetime(2026, 6, 27, 5, 8, tzinfo=UTC)
    assert result.summary.duration_minutes == 368
    assert result.summary.asleep_minutes == 363
    assert result.summary.light_minutes == 180
    assert result.summary.deep_minutes == 135
    assert result.summary.rem_minutes == 48
    assert result.summary.awake_minutes == 5
    assert [sample.value for sample in result.samples] == [
        "light",
        "deep",
        "rem",
        "light",
        "awake",
        "deep",
    ]
    assert result.samples[0].metric is HistoryMetric.SLEEP_STAGE
    assert result.samples[0].timestamp == datetime(2026, 6, 26, 23, 0, tzinfo=UTC)
    assert result.samples[1].timestamp == datetime(2026, 6, 27, 0, 0, tzinfo=UTC)
    assert result.samples[-1].timestamp == datetime(2026, 6, 27, 3, 38, tzinfo=UTC)
