"""REST endpoints for discovery, control, and session history."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..csafe import CsafeError
from ..models import (
    MachineInfo,
    SessionSummary,
    SetResistanceRequest,
    SetSpeedRequest,
    SetTargetPowerRequest,
    StartWorkoutRequest,
    Telemetry,
)

router = APIRouter()


def _manager(request: Request):
    return request.app.state.manager


def _db(request: Request):
    return request.app.state.db


@router.get("/machines", response_model=list[MachineInfo])
async def list_machines(request: Request) -> list[MachineInfo]:
    return _manager(request).list()


@router.get("/machines/{machine_id}", response_model=MachineInfo)
async def get_machine(machine_id: str, request: Request) -> MachineInfo:
    try:
        return _manager(request).get(machine_id).info()
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/machines/{machine_id}/telemetry", response_model=Telemetry)
async def get_telemetry(machine_id: str, request: Request) -> Telemetry:
    try:
        machine = _manager(request).get(machine_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    if machine.last_telemetry is None:
        raise HTTPException(status_code=503, detail="no telemetry yet")
    return machine.last_telemetry


@router.post("/machines/{machine_id}/workout/start")
async def start_workout(
    machine_id: str, body: StartWorkoutRequest, request: Request
) -> dict[str, int]:
    try:
        session_id = await _manager(request).start_session(machine_id, body.user_label)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (CsafeError, RuntimeError) as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {"session_id": session_id}


@router.post("/machines/{machine_id}/workout/stop")
async def stop_workout(machine_id: str, request: Request) -> dict[str, int | None]:
    try:
        session_id = await _manager(request).stop_session(machine_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"session_id": session_id}


@router.post("/machines/{machine_id}/workout/pause")
async def pause_workout(machine_id: str, request: Request) -> dict[str, str]:
    try:
        await _manager(request).get(machine_id).go_paused()
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except CsafeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"status": "paused"}


@router.post("/machines/{machine_id}/resistance")
async def set_resistance(
    machine_id: str, body: SetResistanceRequest, request: Request
) -> dict[str, str]:
    try:
        await _manager(request).get(machine_id).set_resistance(body.level)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except CsafeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"status": "ok"}


@router.post("/machines/{machine_id}/target-power")
async def set_target_power(
    machine_id: str, body: SetTargetPowerRequest, request: Request
) -> dict[str, str]:
    try:
        await _manager(request).get(machine_id).set_target_power(body.watts)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except CsafeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"status": "ok"}


@router.post("/machines/{machine_id}/speed")
async def set_speed(
    machine_id: str, body: SetSpeedRequest, request: Request
) -> dict[str, str]:
    try:
        await _manager(request).get(machine_id).set_speed_kmh(body.kmh)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except CsafeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"status": "ok"}


@router.get("/sessions", response_model=list[SessionSummary])
async def list_sessions(request: Request, limit: int = 50) -> list[SessionSummary]:
    return await _db(request).list_sessions(limit=limit)
