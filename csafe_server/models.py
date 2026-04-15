"""Pydantic DTOs shared by the API layer and persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

MachineKind = Literal["amt", "rbk"]
MachineState = Literal["ready", "in_use", "paused", "finished", "manual", "offline", "error"]


class MachineInfo(BaseModel):
    id: str
    kind: MachineKind
    port: str
    label: str | None = None
    connected: bool
    state: MachineState


class Telemetry(BaseModel):
    """One frame of machine telemetry. All fields are optional – the console
    does not always populate every metric (e.g. HR requires a chest strap)."""

    machine_id: str
    timestamp: datetime
    state: MachineState
    elapsed_sec: int | None = None
    distance_m: float | None = None
    calories: int | None = None
    speed_kmh: float | None = None
    cadence_rpm: int | None = None
    heart_rate_bpm: int | None = None
    power_watts: int | None = None
    grade_pct: float | None = None


class SetResistanceRequest(BaseModel):
    """RBK/AMT resistance level (1-20 on most Precor consoles)."""

    level: int = Field(..., ge=1, le=30)


class SetTargetPowerRequest(BaseModel):
    watts: int = Field(..., ge=0, le=2000)


class SetSpeedRequest(BaseModel):
    """Speed in 0.1 km/h units (AMT stride rate proxy)."""

    kmh: float = Field(..., ge=0.0, le=40.0)


class StartWorkoutRequest(BaseModel):
    user_label: str | None = None


class SessionSummary(BaseModel):
    id: int
    machine_id: str
    machine_kind: MachineKind
    started_at: datetime
    ended_at: datetime | None
    duration_sec: int | None
    distance_m: float | None
    calories: int | None
    avg_power_watts: float | None
    avg_hr_bpm: float | None
    user_label: str | None
