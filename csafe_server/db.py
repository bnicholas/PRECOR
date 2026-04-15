"""SQLite-backed session log.

Two tables:

* ``sessions`` – one row per workout, with roll-up aggregates.
* ``samples``  – raw telemetry rows (one per poll cycle) keyed by session id.

Averages are computed on ``close_session`` in a single pass so the REST
history endpoint doesn't have to scan ``samples``.
"""

from __future__ import annotations

import aiosqlite

from .models import MachineKind, SessionSummary, Telemetry


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id    TEXT    NOT NULL,
    machine_kind  TEXT    NOT NULL,
    started_at    TEXT    NOT NULL,
    ended_at      TEXT,
    duration_sec  INTEGER,
    distance_m    REAL,
    calories      INTEGER,
    avg_power_watts REAL,
    avg_hr_bpm      REAL,
    user_label    TEXT
);

CREATE TABLE IF NOT EXISTS samples (
    session_id      INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    ts              TEXT    NOT NULL,
    elapsed_sec     INTEGER,
    distance_m      REAL,
    calories        INTEGER,
    speed_kmh       REAL,
    cadence_rpm     INTEGER,
    heart_rate_bpm  INTEGER,
    power_watts     INTEGER,
    grade_pct       REAL
);

CREATE INDEX IF NOT EXISTS samples_session_idx ON samples(session_id);
"""


class Database:
    def __init__(self, path: str) -> None:
        self._path = path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if not self._db:
            raise RuntimeError("Database is not connected")
        return self._db

    async def create_session(
        self,
        *,
        machine_id: str,
        machine_kind: MachineKind,
        user_label: str | None,
    ) -> int:
        cur = await self.conn.execute(
            """
            INSERT INTO sessions (machine_id, machine_kind, started_at, user_label)
            VALUES (?, ?, datetime('now'), ?)
            """,
            (machine_id, machine_kind, user_label),
        )
        await self.conn.commit()
        assert cur.lastrowid is not None
        return cur.lastrowid

    async def append_sample(self, session_id: int, t: Telemetry) -> None:
        await self.conn.execute(
            """
            INSERT INTO samples (
                session_id, ts, elapsed_sec, distance_m, calories,
                speed_kmh, cadence_rpm, heart_rate_bpm, power_watts, grade_pct
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                t.timestamp.isoformat(),
                t.elapsed_sec,
                t.distance_m,
                t.calories,
                t.speed_kmh,
                t.cadence_rpm,
                t.heart_rate_bpm,
                t.power_watts,
                t.grade_pct,
            ),
        )
        await self.conn.commit()

    async def close_session(self, session_id: int, final: Telemetry | None) -> None:
        async with self.conn.execute(
            """
            SELECT
                MAX(elapsed_sec) AS duration_sec,
                MAX(distance_m)  AS distance_m,
                MAX(calories)    AS calories,
                AVG(power_watts) AS avg_power_watts,
                AVG(heart_rate_bpm) AS avg_hr_bpm
            FROM samples WHERE session_id = ?
            """,
            (session_id,),
        ) as cur:
            agg = await cur.fetchone()

        await self.conn.execute(
            """
            UPDATE sessions SET
                ended_at        = datetime('now'),
                duration_sec    = ?,
                distance_m      = ?,
                calories        = ?,
                avg_power_watts = ?,
                avg_hr_bpm      = ?
            WHERE id = ?
            """,
            (
                agg["duration_sec"] if agg else None,
                agg["distance_m"] if agg else None,
                agg["calories"] if agg else None,
                agg["avg_power_watts"] if agg else None,
                agg["avg_hr_bpm"] if agg else None,
                session_id,
            ),
        )
        await self.conn.commit()

    async def list_sessions(self, limit: int = 50) -> list[SessionSummary]:
        async with self.conn.execute(
            "SELECT * FROM sessions ORDER BY id DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
        return [SessionSummary(**dict(r)) for r in rows]
