"""WebSocket endpoint for live telemetry streaming.

Clients connect to ``/ws/machines/{id}/telemetry`` and receive JSON messages
of the :class:`Telemetry` shape, one per poll cycle. The first message is the
latest cached sample (if any) so late-joining clients don't see a blank UI.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/machines/{machine_id}/telemetry")
async def telemetry_ws(websocket: WebSocket, machine_id: str) -> None:
    manager = websocket.app.state.manager
    try:
        machine = manager.get(machine_id)
    except KeyError:
        await websocket.close(code=4404, reason=f"unknown machine {machine_id}")
        return

    await websocket.accept()
    try:
        async for telemetry in machine.subscribe():
            await websocket.send_text(telemetry.model_dump_json())
    except WebSocketDisconnect:
        log.debug("ws client disconnected from %s", machine_id)
    except asyncio.CancelledError:
        raise
    except Exception as e:  # pragma: no cover
        log.warning("ws error for %s: %s", machine_id, e)
        with _suppress():
            await websocket.close()


class _suppress:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *args: object) -> bool:
        return True
