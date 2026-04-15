"""Unit tests for CSAFE command encoding / response parsing."""

from __future__ import annotations

import pytest

from csafe_server.csafe.commands import (
    Cmd,
    FrameStatus,
    encode_commands,
    parse_response,
)


class TestEncodeCommands:
    def test_short_commands_only(self) -> None:
        assert encode_commands([(Cmd.GETSTATUS, b""), (Cmd.GETSPEED, b"")]) == bytes(
            [0x80, 0xA5]
        )

    def test_long_command_with_data(self) -> None:
        assert encode_commands([(Cmd.SETGEAR, bytes([0x05]))]) == bytes([0x29, 0x01, 0x05])

    def test_short_with_data_rejected(self) -> None:
        with pytest.raises(ValueError):
            encode_commands([(Cmd.GETSTATUS, b"\x01")])


class TestParseResponse:
    def test_empty_payload(self) -> None:
        snap = parse_response(b"")
        assert snap.status == FrameStatus.OFFLINE

    def test_status_only(self) -> None:
        # Status byte low nibble = IN_USE.
        snap = parse_response(bytes([0x12]))
        assert snap.status == FrameStatus.IN_USE

    def test_speed_field(self) -> None:
        # status=READY, opcode GETSPEED (0xA5) len=2 value=0x00F0 (240 -> 24.0 km/h)
        payload = bytes([0x01, 0xA5, 0x02, 0xF0, 0x00])
        snap = parse_response(payload)
        assert snap.speed_kmh == pytest.approx(24.0)

    def test_hr_and_power(self) -> None:
        payload = bytes([
            0x01,
            0xB0, 0x01, 148,           # HR = 148 bpm
            0xB4, 0x02, 0x2C, 0x01,    # POWER = 300 W
        ])
        snap = parse_response(payload)
        assert snap.heart_rate_bpm == 148
        assert snap.power_watts == 300

    def test_elapsed_time(self) -> None:
        # 1h 02m 03s
        payload = bytes([0x01, 0xA0, 0x03, 1, 2, 3])
        snap = parse_response(payload)
        assert snap.elapsed_sec == 3723

    def test_tolerates_truncated_field(self) -> None:
        # Length says 4 but only 1 byte available -> parser bails cleanly.
        payload = bytes([0x01, 0xA5, 0x04, 0xAA])
        snap = parse_response(payload)
        assert snap.speed_kmh is None
