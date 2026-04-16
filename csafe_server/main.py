"""FastAPI entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import rest, ws
from .config import settings
from .db import Database
from .manager import MachineManager


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(settings.db_path)
        await db.connect()
        manager = MachineManager(
            settings.machine_configs(),
            db,
            poll_interval=settings.telemetry_interval,
            command_timeout=settings.command_timeout,
            keepalive_interval=settings.keepalive_interval,
        )
        await manager.start()
        app.state.db = db
        app.state.manager = manager
        try:
            yield
        finally:
            await manager.stop()
            await db.close()

    app = FastAPI(title="Precor CSAFE Gateway", version="0.1.0", lifespan=lifespan)
    # RN app dev clients come from arbitrary LAN origins; lock this down in prod.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(rest.router, prefix="/api")
    app.include_router(ws.router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(
        "csafe_server.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
