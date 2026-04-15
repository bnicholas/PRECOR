"""CSAFE command opcodes and response parsing.

CSAFE payloads are sequences of commands. Two flavours exist:

* **Short commands** (opcode 0x80–0xFF): just the opcode, no data.
* **Long commands** (opcode 0x01–0x7F): opcode, 1-byte length, ``length`` bytes
  of data.

A response frame echoes the current status byte first, then for each command
in the request returns the opcode, a length byte, and ``length`` bytes of data
(for GET commands) or nothing further (for SET/short status commands, though
many equipment implementations still include an empty length field).

The opcodes below are the subset needed to drive the Precor P80 AMT and RBK.
The P80 follows standard CSAFE for the telemetry most useful to a client
(status, speed/pace/cadence, power, heart rate, distance, calories, elapsed
time). SET commands and a handful of opcodes vary across vendors; those are
grouped separately and documented as "verify against your console".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Iterable


class Cmd(IntEnum):
    """CSAFE command opcodes (subset)."""

    # --- Short status / state transition commands (0x80-0x9F) ---
    GETSTATUS = 0x80
    RESET = 0x81
    GOIDLE = 0x82
    GOHAVEID = 0x83
    GOINUSE = 0x85
    GOFINISHED = 0x86
    GOREADY = 0x87

    # --- Short GET commands (data returned in the response) ---
    GETVERSION = 0x91
    GETID = 0x92
    GETUNITS = 0x93
    GETSERIAL = 0x94
    GETODOMETER = 0x9B
    GETERRORCODE = 0x9C
    GETSERVICECODE = 0x9D
    GETUSERCFG1 = 0x9E
    GETUSERCFG2 = 0x9F

    GETTWORK = 0xA0         # elapsed time, 3 bytes (hh,mm,ss)
    GETHORIZONTAL = 0xA1    # distance, 2 bytes + units byte
    GETVERTICAL = 0xA2
    GETCALORIES = 0xA3      # 2 bytes kcal
    GETPROGRAM = 0xA4
    GETSPEED = 0xA5         # 2 bytes, units e.g. 0.1 km/h
    GETPACE = 0xA6
    GETCADENCE = 0xA7       # 2 bytes rpm / spm
    GETGRADE = 0xA8
    GETGEAR = 0xA9
    GETUPLIST = 0xAA
    GETUSERINFO = 0xAB
    GETTORQUE = 0xAC

    GETHRCUR = 0xB0         # 1 byte bpm
    GETHRTZONE = 0xB1
    GETHRMAX = 0xB2
    GETHRSUM = 0xB3
    GETPOWER = 0xB4         # 2 bytes watts

    # --- Long SET commands (take data; verify against P80 before relying on) ---
    SETTIME = 0x11
    SETDATE = 0x12
    SETTIMEOUT = 0x13
    SETPROGRAM = 0x24
    SETSPEED = 0x26
    SETGRADE = 0x28
    SETGEAR = 0x29
    SETUSERCFG1 = 0x2A
    SETTWORK = 0x20
    SETTWORKDIST = 0x21
    SETTWORKCAL = 0x23
    SETPOWER = 0x34


SHORT_CMD_MIN = 0x80


def is_short(opcode: int) -> bool:
    return opcode >= SHORT_CMD_MIN


def encode_commands(commands: Iterable[tuple[int, bytes]]) -> bytes:
    """Encode an iterable of ``(opcode, data)`` tuples into a CSAFE payload.

    ``data`` must be empty for short commands (opcode >= 0x80).
    """
    out = bytearray()
    for opcode, data in commands:
        if is_short(opcode):
            if data:
                raise ValueError(f"short command 0x{opcode:02X} cannot carry data")
            out.append(opcode)
        else:
            if len(data) > 0xFF:
                raise ValueError(f"long command data too long ({len(data)})")
            out.append(opcode)
            out.append(len(data))
            out.extend(data)
    return bytes(out)


# --- Response parsing ---------------------------------------------------------


class FrameStatus(IntEnum):
    """Decoded meaning of the status byte at the head of a response payload.

    CSAFE encodes the prev-frame-OK flag, frame count, and machine state in a
    single byte. Only the state nibble is interesting to most clients.
    """

    ERROR = 0x0
    READY = 0x1
    IN_USE = 0x2
    PAUSED = 0x3
    FINISHED = 0x4
    MANUAL = 0x5
    OFFLINE = 0x6

    @classmethod
    def from_byte(cls, b: int) -> "FrameStatus":
        nibble = b & 0x0F
        try:
            return cls(nibble)
        except ValueError:
            return cls.ERROR


@dataclass(slots=True)
class MachineSnapshot:
    """Parsed telemetry from one response frame."""

    status: FrameStatus = FrameStatus.OFFLINE
    elapsed_sec: int | None = None
    distance_m: float | None = None
    calories: int | None = None
    speed_kmh: float | None = None
    cadence_rpm: int | None = None
    heart_rate_bpm: int | None = None
    power_watts: int | None = None
    grade_pct: float | None = None
    raw: dict[int, bytes] = field(default_factory=dict)

    def merge(self, other: "MachineSnapshot") -> "MachineSnapshot":
        """Field-wise merge; ``other`` wins where it has non-None values."""
        for f in (
            "status",
            "elapsed_sec",
            "distance_m",
            "calories",
            "speed_kmh",
            "cadence_rpm",
            "heart_rate_bpm",
            "power_watts",
            "grade_pct",
        ):
            v = getattr(other, f)
            if v is not None and (f != "status" or v != FrameStatus.OFFLINE):
                setattr(self, f, v)
        self.raw.update(other.raw)
        return self


def _u16_le(data: bytes, offset: int = 0) -> int:
    return data[offset] | (data[offset + 1] << 8)


def parse_response(payload: bytes) -> MachineSnapshot:
    """Parse a response payload into a :class:`MachineSnapshot`.

    The first byte is the status byte; the remainder is a sequence of
    ``opcode, length, data[length]`` triplets (even for short commands the
    console typically replies with a length-prefixed data block).
    """
    snap = MachineSnapshot()
    if not payload:
        return snap
    snap.status = FrameStatus.from_byte(payload[0])
    i = 1
    n = len(payload)
    while i < n:
        opcode = payload[i]
        i += 1
        if i >= n:
            break
        length = payload[i]
        i += 1
        if i + length > n:
            break
        data = payload[i : i + length]
        i += length
        snap.raw[opcode] = data
        _apply_field(snap, opcode, data)
    return snap


def _apply_field(snap: MachineSnapshot, opcode: int, data: bytes) -> None:
    """Decode a single response field onto the snapshot."""
    try:
        if opcode == Cmd.GETTWORK and len(data) >= 3:
            h, m, s = data[0], data[1], data[2]
            snap.elapsed_sec = h * 3600 + m * 60 + s
        elif opcode == Cmd.GETHORIZONTAL and len(data) >= 3:
            # 2-byte distance in the units reported by the 3rd byte.
            # P80 returns meters (units byte = 0x24) most commonly.
            raw = _u16_le(data)
            units = data[2] if len(data) >= 3 else 0x24
            snap.distance_m = float(raw) if units == 0x24 else float(raw)
        elif opcode == Cmd.GETCALORIES and len(data) >= 2:
            snap.calories = _u16_le(data)
        elif opcode == Cmd.GETSPEED and len(data) >= 2:
            # Typically 0.1 km/h resolution.
            snap.speed_kmh = _u16_le(data) / 10.0
        elif opcode == Cmd.GETCADENCE and len(data) >= 2:
            snap.cadence_rpm = _u16_le(data)
        elif opcode == Cmd.GETHRCUR and len(data) >= 1:
            snap.heart_rate_bpm = data[0]
        elif opcode == Cmd.GETPOWER and len(data) >= 2:
            snap.power_watts = _u16_le(data)
        elif opcode == Cmd.GETGRADE and len(data) >= 2:
            # 0.1 % resolution, signed.
            raw = _u16_le(data)
            if raw & 0x8000:
                raw -= 0x10000
            snap.grade_pct = raw / 10.0
    except (IndexError, ValueError):
        # Tolerate malformed field data; keep the raw bytes for diagnostics.
        pass


def build_get_telemetry() -> bytes:
    """Build the standard polling payload used by the telemetry loop."""
    return encode_commands(
        [
            (Cmd.GETSTATUS, b""),
            (Cmd.GETTWORK, b""),
            (Cmd.GETHORIZONTAL, b""),
            (Cmd.GETCALORIES, b""),
            (Cmd.GETSPEED, b""),
            (Cmd.GETCADENCE, b""),
            (Cmd.GETHRCUR, b""),
            (Cmd.GETPOWER, b""),
        ]
    )
