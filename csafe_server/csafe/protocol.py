"""CSAFE framing, byte-stuffing and checksum.

Wire format of a standard frame:

    F0 <stuffed payload> <stuffed checksum> F2

Where:

* ``F0`` is the standard-frame start byte. ``F1`` is the extended-frame start
  byte (same body structure with an added destination/source prefix).
* The **checksum** is the XOR of every unstuffed payload byte.
* **Byte stuffing** escapes the reserved bytes ``F0..F3`` inside the payload
  and checksum: the byte is replaced by ``F3 xx`` where ``xx = byte - 0xF0``.
  So ``F0 -> F3 00``, ``F1 -> F3 01``, ``F2 -> F3 02``, ``F3 -> F3 03``.

This module implements only the raw framing/stuffing. Command-specific
payload construction and parsing live in :mod:`csafe_server.csafe.commands`.
"""

from __future__ import annotations

CSAFE_STD_START = 0xF0
CSAFE_EXT_START = 0xF1
CSAFE_END = 0xF2
CSAFE_ESCAPE = 0xF3

_RESERVED = {CSAFE_STD_START, CSAFE_EXT_START, CSAFE_END, CSAFE_ESCAPE}


class CsafeError(Exception):
    """Base class for CSAFE-related errors."""


class CsafeFramingError(CsafeError):
    """Malformed frame on the wire."""


def xor_checksum(data: bytes) -> int:
    c = 0
    for b in data:
        c ^= b
    return c & 0xFF


def stuff(data: bytes) -> bytes:
    """Apply CSAFE byte-stuffing to ``data``."""
    out = bytearray()
    for b in data:
        if b in _RESERVED:
            out.append(CSAFE_ESCAPE)
            out.append(b - 0xF0)
        else:
            out.append(b)
    return bytes(out)


def unstuff(data: bytes) -> bytes:
    """Reverse CSAFE byte-stuffing. Raises on dangling / invalid escapes."""
    out = bytearray()
    it = iter(data)
    for b in it:
        if b == CSAFE_ESCAPE:
            try:
                n = next(it)
            except StopIteration as e:
                raise CsafeFramingError("dangling escape byte") from e
            if n > 0x03:
                raise CsafeFramingError(f"invalid escape sequence F3 {n:02X}")
            out.append(0xF0 + n)
        else:
            out.append(b)
    return bytes(out)


def build_frame(payload: bytes, *, extended: bool = False) -> bytes:
    """Wrap ``payload`` in a CSAFE frame (start, stuffed body+checksum, end)."""
    start = CSAFE_EXT_START if extended else CSAFE_STD_START
    checksum = xor_checksum(payload)
    body = stuff(payload + bytes([checksum]))
    return bytes([start]) + body + bytes([CSAFE_END])


def parse_frame(frame: bytes) -> tuple[int, bytes]:
    """Return ``(start_byte, payload)`` for a well-formed frame.

    Raises :class:`CsafeFramingError` on any integrity problem (bad start/end
    marker, checksum mismatch, truncated payload, invalid stuffing).
    """
    if len(frame) < 3:
        raise CsafeFramingError("frame too short")
    start = frame[0]
    if start not in (CSAFE_STD_START, CSAFE_EXT_START):
        raise CsafeFramingError(f"invalid start byte 0x{start:02X}")
    if frame[-1] != CSAFE_END:
        raise CsafeFramingError(f"invalid end byte 0x{frame[-1]:02X}")
    unstuffed = unstuff(frame[1:-1])
    if len(unstuffed) < 1:
        raise CsafeFramingError("empty frame body")
    payload, checksum = unstuffed[:-1], unstuffed[-1]
    if xor_checksum(payload) != checksum:
        raise CsafeFramingError("checksum mismatch")
    return start, payload


class FrameReader:
    """Accumulates bytes and yields complete frames.

    CSAFE frames are self-delimited by ``F2`` so a stream parser is trivial:
    buffer until ``F2`` is seen, then parse. Anything that fails to parse is
    discarded so a single bad frame doesn't wedge the stream.
    """

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> list[bytes]:
        """Append bytes; return any fully-parsed payloads (unstuffed, no checksum)."""
        self._buf.extend(chunk)
        frames: list[bytes] = []
        while True:
            try:
                end = self._buf.index(CSAFE_END)
            except ValueError:
                break
            raw = bytes(self._buf[: end + 1])
            del self._buf[: end + 1]
            # Trim any junk before the start byte.
            for i, b in enumerate(raw):
                if b in (CSAFE_STD_START, CSAFE_EXT_START):
                    raw = raw[i:]
                    break
            else:
                continue
            try:
                _, payload = parse_frame(raw)
                frames.append(payload)
            except CsafeFramingError:
                # Discard and continue; next frame may still be intact.
                continue
        return frames
