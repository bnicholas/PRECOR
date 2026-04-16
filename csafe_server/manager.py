"""Registry that owns all configured Machines and brokers session tracking."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from .config import MachineConfig
from .db import Database
from .machine import Machine
from .models import MachineInfo, Telemetry

log = logging.getLogger(__name__)


class MachineManager:
    def __init__(
        self,
        configs: list[MachineConfig],
        db: Database,
        *,
        poll_interval: float,
        command_timeout: float,
        keepalive_interval: float = 0.0,
    ) -> None:
        self._machines: dict[str, Machine] = {
            c.id: Machine(
                c,
                poll_interval=poll_interval,
                command_timeout=command_timeout,
                keepalive_interval=keepalive_interval,
            )
            for c in configs
        }
        self._db = db
        self._active_session: dict[str, int] = {}  # machine_id -> session id
        self._recorder_tasks: dict[str, asyncio.Task[None]] = {}

    async def start(self) -> None:
        await asyncio.gather(*(m.open() for m in self._machines.values()))

    async def stop(self) -> None:
        for task in self._recorder_tasks.values():
            task.cancel()
        await asyncio.gather(
            *(m.close() for m in self._machines.values()), return_exceptions=True
        )

    # -- Lookup ---------------------------------------------------------------

    def list(self) -> list[MachineInfo]:
        return [m.info() for m in self._machines.values()]

    def get(self, machine_id: str) -> Machine:
        try:
            return self._machines[machine_id]
        except KeyError as e:
            raise KeyError(f"unknown machine {machine_id!r}") from e

    # -- Session lifecycle ----------------------------------------------------

    async def start_session(self, machine_id: str, user_label: str | None) -> int:
        machine = self.get(machine_id)
        if machine_id in self._active_session:
            raise RuntimeError(f"{machine_id} already has an active session")
        await machine.reset()
        await machine.go_ready()
        await machine.go_in_use()
        session_id = await self._db.create_session(
            machine_id=machine.cfg.id,
            machine_kind=machine.cfg.kind,
            user_label=user_label,
        )
        self._active_session[machine_id] = session_id
        self._recorder_tasks[machine_id] = asyncio.create_task(
            self._record_loop(machine, session_id),
            name=f"record-{machine_id}",
        )
        return session_id

    async def stop_session(self, machine_id: str) -> int | None:
        session_id = self._active_session.pop(machine_id, None)
        if session_id is None:
            return None
        task = self._recorder_tasks.pop(machine_id, None)
        if task:
            task.cancel()
        machine = self.get(machine_id)
        try:
            await machine.go_finished()
        except Exception as e:  # pragma: no cover
            log.warning("failed to send GOFINISHED to %s: %s", machine_id, e)
        await self._db.close_session(session_id, machine.last_telemetry)
        return session_id

    async def _record_loop(self, machine: Machine, session_id: int) -> None:
        async for telemetry in machine.subscribe():
            try:
                await self._db.append_sample(session_id, telemetry)
            except Exception as e:  # pragma: no cover
                log.warning("failed to persist sample for %s: %s", machine.cfg.id, e)

    # -- Telemetry fan-out ----------------------------------------------------

    async def subscribe(self, machine_id: str) -> AsyncIterator[Telemetry]:
        machine = self.get(machine_id)
        async for t in machine.subscribe():
            yield t
