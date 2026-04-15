"""Unit tests for the CSAFE framing layer."""

from __future__ import annotations

import pytest

from csafe_server.csafe.protocol import (
    CSAFE_END,
    CSAFE_ESCAPE,
    CSAFE_STD_START,
    CsafeFramingError,
    FrameReader,
    build_frame,
    parse_frame,
    stuff,
    unstuff,
    xor_checksum,
)


class TestByteStuffing:
    def test_passthrough(self) -> None:
        assert stuff(b"\x01\x02\x03") == b"\x01\x02\x03"

    def test_escapes_reserved(self) -> None:
        assert stuff(bytes([0xF0])) == bytes([CSAFE_ESCAPE, 0x00])
        assert stuff(bytes([0xF1])) == bytes([CSAFE_ESCAPE, 0x01])
        assert stuff(bytes([0xF2])) == bytes([CSAFE_ESCAPE, 0x02])
        assert stuff(bytes([0xF3])) == bytes([CSAFE_ESCAPE, 0x03])

    def test_roundtrip_all_bytes(self) -> None:
        data = bytes(range(256))
        assert unstuff(stuff(data)) == data

    def test_unstuff_rejects_dangling_escape(self) -> None:
        with pytest.raises(CsafeFramingError):
            unstuff(bytes([CSAFE_ESCAPE]))

    def test_unstuff_rejects_invalid_escape(self) -> None:
        with pytest.raises(CsafeFramingError):
            unstuff(bytes([CSAFE_ESCAPE, 0x05]))


class TestChecksum:
    def test_empty(self) -> None:
        assert xor_checksum(b"") == 0

    def test_known_value(self) -> None:
        # 0x80 ^ 0xA5 ^ 0xB4 = 0x91
        assert xor_checksum(bytes([0x80, 0xA5, 0xB4])) == 0x91


class TestFraming:
    def test_build_and_parse_roundtrip(self) -> None:
        payload = bytes([0x80, 0xA5, 0x00])  # GETSTATUS + GETSPEED short cmds
        frame = build_frame(payload)
        assert frame[0] == CSAFE_STD_START
        assert frame[-1] == CSAFE_END
        start, got = parse_frame(frame)
        assert start == CSAFE_STD_START
        assert got == payload

    def test_parse_rejects_bad_start(self) -> None:
        with pytest.raises(CsafeFramingError):
            parse_frame(bytes([0xFF, 0x00, CSAFE_END]))

    def test_parse_rejects_bad_end(self) -> None:
        with pytest.raises(CsafeFramingError):
            parse_frame(bytes([CSAFE_STD_START, 0x00, 0x00, 0xFF]))

    def test_parse_rejects_bad_checksum(self) -> None:
        # Manually craft a frame with a wrong checksum.
        payload = bytes([0x80])
        bad = bytes([CSAFE_STD_START]) + payload + bytes([0x00, CSAFE_END])
        with pytest.raises(CsafeFramingError):
            parse_frame(bad)

    def test_stuffed_reserved_byte_in_payload(self) -> None:
        # A checksum that happens to equal F2 should still round-trip.
        # 0xF0 ^ 0x02 = 0xF2 -> forces escape in the checksum position.
        payload = bytes([0xF0, 0x02])
        frame = build_frame(payload)
        # The checksum 0xF2 must have been escaped as F3 02.
        assert bytes([CSAFE_ESCAPE, 0x02]) in frame
        _, got = parse_frame(frame)
        assert got == payload


class TestFrameReader:
    def test_single_frame(self) -> None:
        payload = bytes([0x80, 0xA5])
        frame = build_frame(payload)
        r = FrameReader()
        assert r.feed(frame) == [payload]

    def test_chunked(self) -> None:
        payload = bytes([0x80, 0xA5, 0xB4])
        frame = build_frame(payload)
        r = FrameReader()
        out: list[bytes] = []
        for b in frame:
            out.extend(r.feed(bytes([b])))
        assert out == [payload]

    def test_back_to_back_frames(self) -> None:
        p1 = bytes([0x80])
        p2 = bytes([0xA5, 0xA7])
        r = FrameReader()
        result = r.feed(build_frame(p1) + build_frame(p2))
        assert result == [p1, p2]

    def test_skips_garbage_before_start(self) -> None:
        payload = bytes([0x80])
        r = FrameReader()
        # Leading junk without F2 is buffered; once a frame ends we keep going.
        result = r.feed(b"\x00\x11\x22" + build_frame(payload))
        assert result == [payload]

    def test_drops_corrupt_frame_and_recovers(self) -> None:
        good = build_frame(bytes([0x80]))
        # Corrupt frame: valid markers, wrong checksum.
        bad = bytes([CSAFE_STD_START, 0x80, 0x00, CSAFE_END])
        r = FrameReader()
        result = r.feed(bad + good)
        assert result == [bytes([0x80])]
