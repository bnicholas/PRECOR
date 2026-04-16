"""Async wrapper around a single CSAFE-connected console.

Each :class:`Machine` owns a serial port, a mutex around request/response
exchanges, and a background task that polls for telemetry and publishes
snapshots to any subscribed asyncio queues.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from datetime import datetime, timezone
from typing import AsyncIterator

import serial_asyncio  # type: ignore[import-untyped]

from .config import MachineConfig
from .csafe import (
    Cmd,
    CsafeError,
    FrameStatus,
    MachineSnapshot,
    build_frame,
    build_get_telemetry,
    parse_frame,
)
from .csafe.commands import encode_commands
from .csafe.protocol import FrameReader
from .models import MachineInfo, MachineState, Telemetry

log = logging.getLogger(__name__)

_STATUS_TO_STATE: dict[FrameStatus, MachineState] = {
    FrameStatus.ERROR: "error",
    FrameStatus.READY: "ready",
    FrameStatus.IN_USE: "in_use",
    FrameStatus.PAUSED: "paused",
    FrameStatus.FINISHED: "finished",
    FrameStatus.MANUAL: "manual",
    FrameStatus.OFFLINE: "offline",
}


class Machine:
    def __init__(
        self,
        cfg: MachineConfig,
        *,
        poll_interval: float,
        command_timeout: float,
        keepalive_interval: float = 0.0,
    ) -> None:
        self.cfg = cfg
        self._poll_interval = poll_interval
        self._command_timeout = command_timeout
        self._keepalive_interval = keepalive_interval

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._frame_reader = FrameReader()

        self._io_lock = asyncio.Lock()
        self._poll_task: asyncio.Task[None] | None = None
        self._keepalive_task: asyncio.Task[None] | None = None
        self._subscribers: set[asyncio.Queue[Telemetry]] = set()

        self._last: Telemetry | None = None
        self._last_tx_mono: float = 0.0
        self._connected = False

    # -- Connection lifecycle -------------------------------------------------

    async def open(self) -> None:
        try:
            self._reader, self._writer = await serial_asyncio.open_serial_connection(
                url=self.cfg.port, baudrate=self.cfg.baud
            )
            self._connected = True
            log.info("opened %s on %s", self.cfg.id, self.cfg.port)
        except Exception as e:  # pragma: no cover - hardware-dependent
            self._connected = False
            log.warning("failed to open %s on %s: %s", self.cfg.id, self.cfg.port, e)
            return
        self._last_tx_mono = time.monotonic()
        self._poll_task = asyncio.create_task(
            self._poll_loop(), name=f"poll-{self.cfg.id}"
        )
        if self._keepalive_interval > 0:
            self._keepalive_task = asyncio.create_task(
                self._keepalive_loop(), name=f"keepalive-{self.cfg.id}"
            )

    async def close(self) -> None:
        for task in (self._keepalive_task, self._poll_task):
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        self._poll_task = None
        self._keepalive_task = None
        if self._writer:
            self._writer.close()
            with suppress(Exception):
                await self._writer.wait_closed()
        self._reader = None
        self._writer = None
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def info(self) -> MachineInfo:
        state: MachineState = (self._last.state if self._last else "offline")
        return MachineInfo(
            id=self.cfg.id,
            kind=self.cfg.kind,
            port=self.cfg.port,
            label=self.cfg.label,
            connected=self._connected,
            state=state,
        )

    @property
    def last_telemetry(self) -> Telemetry | None:
        return self._last

    # -- Request/response -----------------------------------------------------

    async def _write_frame(self, frame: bytes) -> None:
        """Write a pre-built CSAFE frame. Caller must hold ``_io_lock``."""
        assert self._writer is not None
        self._writer.write(frame)
        await self._writer.drain()
        self._last_tx_mono = time.monotonic()

    async def exchange(self, commands: list[tuple[int, bytes]]) -> MachineSnapshot:
        """Send a command list and return the parsed response snapshot."""
        if not self._connected or not self._writer or not self._reader:
            raise CsafeError(f"machine {self.cfg.id} is not connected")

        payload = encode_commands(commands)
        frame = build_frame(payload)

        async with self._io_lock:
            await self._write_frame(frame)
            try:
                response = await asyncio.wait_for(
                    self._read_one_frame(), timeout=self._command_timeout
                )
            except asyncio.TimeoutError as e:
                raise CsafeError(f"timeout waiting for {self.cfg.id} response") from e

        from .csafe.commands import parse_response  # late import to avoid cycles
        return parse_response(response)

    async def _read_one_frame(self) -> bytes:
        assert self._reader is not None
        while True:
            chunk = await self._reader.read(256)
            if not chunk:
                raise CsafeError("serial EOF")
            frames = self._frame_reader.feed(chunk)
            if frames:
                # If the console pipelined multiple frames, keep the first.
                return frames[0]

    # -- Telemetry polling ----------------------------------------------------

    async def _poll_loop(self) -> None:
        payload = build_get_telemetry()
        frame = build_frame(payload)
        while True:
            try:
                async with self._io_lock:
                    assert self._writer is not None and self._reader is not None
                    await self._write_frame(frame)
                    raw = await asyncio.wait_for(
                        self._read_one_frame(), timeout=self._command_timeout
                    )
                from .csafe.commands import parse_response
                snap = parse_response(raw)
                self._last = self._snapshot_to_telemetry(snap)
                await self._broadcast(self._last)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.debug("poll error on %s: %s", self.cfg.id, e)
            await asyncio.sleep(self._poll_interval)

    async def _keepalive_loop(self) -> None:
        """Send a GETSTATUS if the link has been silent for too long.

        Useful for headless (no-P80) operation in case the lower I/O board
        firmware goes quiet without a peer. The poll loop normally keeps the
        bus warm on its own; this task only fires when nothing else has
        talked for ``keepalive_interval`` seconds.
        """
        # Check a few times per interval so we react quickly after an idle.
        tick = max(0.5, self._keepalive_interval / 3)
        while True:
            await asyncio.sleep(tick)
            idle = time.monotonic() - self._last_tx_mono
            if idle < self._keepalive_interval:
                continue
            try:
                await self.exchange([(Cmd.GETSTATUS, b"")])
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.debug("keepalive error on %s: %s", self.cfg.id, e)

    def _snapshot_to_telemetry(self, snap: MachineSnapshot) -> Telemetry:
        return Telemetry(
            machine_id=self.cfg.id,
            timestamp=datetime.now(timezone.utc),
            state=_STATUS_TO_STATE.get(snap.status, "error"),
            elapsed_sec=snap.elapsed_sec,
            distance_m=snap.distance_m,
            calories=snap.calories,
            speed_kmh=snap.speed_kmh,
            cadence_rpm=snap.cadence_rpm,
            heart_rate_bpm=snap.heart_rate_bpm,
            power_watts=snap.power_watts,
            grade_pct=snap.grade_pct,
        )

    async def _broadcast(self, t: Telemetry) -> None:
        dead: list[asyncio.Queue[Telemetry]] = []
        for q in self._subscribers:
            try:
                q.put_nowait(t)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.discard(q)

    async def subscribe(self) -> AsyncIterator[Telemetry]:
        q: asyncio.Queue[Telemetry] = asyncio.Queue(maxsize=16)
        self._subscribers.add(q)
        try:
            if self._last is not None:
                await q.put(self._last)
            while True:
                yield await q.get()
        finally:
            self._subscribers.discard(q)

    # -- High-level control ---------------------------------------------------

    async def reset(self) -> MachineSnapshot:
        return await self.exchange([(Cmd.RESET, b"")])

    async def go_ready(self) -> MachineSnapshot:
        return await self.exchange([(Cmd.GOREADY, b"")])

    async def go_in_use(self) -> MachineSnapshot:
        return await self.exchange([(Cmd.GOINUSE, b"")])

    async def go_paused(self) -> MachineSnapshot:
        # CSAFE doesn't have a dedicated PAUSE short; GOFINISHED then GOREADY is
        # the safe portable sequence. Many P80 firmwares accept GOFINISHED alone.
        return await self.exchange([(Cmd.GOFINISHED, b"")])

    async def go_finished(self) -> MachineSnapshot:
        return await self.exchange([(Cmd.GOFINISHED, b"")])

    async def set_resistance(self, level: int) -> MachineSnapshot:
        # RBK / AMT resistance is conveyed via SETGEAR on the P80.
        return await self.exchange([(Cmd.SETGEAR, bytes([level & 0xFF]))])

    async def set_target_power(self, watts: int) -> MachineSnapshot:
        data = bytes([watts & 0xFF, (watts >> 8) & 0xFF])
        return await self.exchange([(Cmd.SETPOWER, data)])

    async def set_speed_kmh(self, kmh: float) -> MachineSnapshot:
        raw = int(round(kmh * 10))
        data = bytes([raw & 0xFF, (raw >> 8) & 0xFF, 0x18])  # 0x18 = km/h units
        return await self.exchange([(Cmd.SETSPEED, data)])
