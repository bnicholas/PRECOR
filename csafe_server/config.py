"""Runtime configuration.

Settings are loaded from environment variables (optionally a .env file).
Machine wiring is declared here: each entry maps a logical machine id
(stable across restarts, used by the REST/WS API) to a serial port path
and a machine kind (``amt`` or ``rbk``).

The default mapping assumes two USB-to-RS232 adapters on a Raspberry Pi.
Overlay the defaults with the ``CSAFE_MACHINES`` env var if needed:

    CSAFE_MACHINES='[{"id":"amt","kind":"amt","port":"/dev/ttyUSB0"},
                     {"id":"rbk","kind":"rbk","port":"/dev/ttyUSB1"}]'
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

MachineKind = Literal["amt", "rbk"]


class MachineConfig(BaseModel):
    """Static wiring for one CSAFE-connected console."""

    id: str = Field(..., description="Stable logical id used by the API.")
    kind: MachineKind
    port: str = Field(..., description="Serial device path, e.g. /dev/ttyUSB0")
    baud: int = 9600
    label: str | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CSAFE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 8080

    # Poll interval for streaming telemetry (seconds).
    telemetry_interval: float = 1.0

    # Command response timeout on the serial link (seconds).
    command_timeout: float = 1.5

    # SQLite DB location for workout session persistence.
    db_path: str = "csafe.sqlite"

    # JSON-encoded list of MachineConfig. Falls back to sensible defaults.
    machines: str = ""

    def machine_configs(self) -> list[MachineConfig]:
        if not self.machines.strip():
            return [
                MachineConfig(id="amt", kind="amt", port="/dev/ttyUSB0", label="Precor AMT"),
                MachineConfig(id="rbk", kind="rbk", port="/dev/ttyUSB1", label="Precor RBK"),
            ]
        raw = json.loads(self.machines)
        return [MachineConfig(**m) for m in raw]


settings = Settings()
