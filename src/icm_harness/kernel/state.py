from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from icm_harness.kernel.errors import InvalidTransition, LeaseLost, LeaseUnavailable


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


@dataclass(frozen=True, slots=True)
class RoundRecord:
    round_id: str
    objective: str
    route: tuple[str, ...]
    stages: tuple[str, ...]
    cursor: int
    status: str
    version: int
    created_at: str
    updated_at: str
    profile: Mapping[str, Any] | None = None
    route_reason: str = ""
    active_gate: str | None = None
    cancel_requested: bool = False
    last_error: str | None = None
    workspace_path: str | None = None

    @property
    def current_stage(self) -> str | None:
        return None if self.cursor >= len(self.stages) else self.stages[self.cursor]


@dataclass(frozen=True, slots=True)
class EventRecord:
    id: int
    round_id: str
    stage_ref: str | None
    kind: str
    payload: Mapping[str, Any]
    created_at: str


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    id: int
    round_id: str
    stage_ref: str
    name: str
    relative_path: str
    media_type: str
    sha256: str
    size: int
    created_at: str


class SQLiteStateStore:
    """SQLite state with WAL, optimistic versioning, and expiring resource leases."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS rounds (
                round_id TEXT PRIMARY KEY,
                objective TEXT NOT NULL,
                route_json TEXT NOT NULL,
                stages_json TEXT NOT NULL,
                cursor INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS leases (
                resource_key TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                acquired_at TEXT NOT NULL,
                heartbeat_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS stage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round_id TEXT NOT NULL,
                stage_ref TEXT,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round_id TEXT NOT NULL,
                stage_ref TEXT NOT NULL,
                name TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                media_type TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                size INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(round_id, stage_ref, name)
            );
            CREATE INDEX IF NOT EXISTS idx_stage_events_round_id
                ON stage_events(round_id, id);
            CREATE INDEX IF NOT EXISTS idx_artifacts_round_id
                ON artifacts(round_id, id);
            """)

            columns = {row[1] for row in conn.execute("PRAGMA table_info(rounds)")}
            migrations = {
                "profile_json": "TEXT NOT NULL DEFAULT '{}'",
                "route_reason": "TEXT NOT NULL DEFAULT ''",
                "active_gate": "TEXT",
                "cancel_requested": "INTEGER NOT NULL DEFAULT 0",
                "last_error": "TEXT",
                "workspace_path": "TEXT",
            }
            for name, declaration in migrations.items():
                if name not in columns:
                    conn.execute(f"ALTER TABLE rounds ADD COLUMN {name} {declaration}")

    def create_round(
        self,
        round_id: str,
        objective: str,
        route: Iterable[str],
        stages: Iterable[str],
        *,
        profile: Mapping[str, Any] | None = None,
        route_reason: str = "",
    ) -> RoundRecord:
        now = _iso(_utcnow())
        route_t, stages_t = tuple(route), tuple(stages)
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO rounds(
                    round_id, objective, route_json, stages_json, cursor, status, version,
                    created_at, updated_at, profile_json, route_reason, cancel_requested
                ) VALUES (?, ?, ?, ?, 0, 'active', 1, ?, ?, ?, ?, 0)""",
                (
                    round_id,
                    objective,
                    json.dumps(route_t),
                    json.dumps(stages_t),
                    now,
                    now,
                    json.dumps(profile or {}, sort_keys=True),
                    route_reason,
                ),
            )
        return self.get_round(round_id)

    def get_round(self, round_id: str) -> RoundRecord:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM rounds WHERE round_id = ?", (round_id,)).fetchone()
        if row is None:
            raise KeyError(round_id)
        return RoundRecord(
            row["round_id"],
            row["objective"],
            tuple(json.loads(row["route_json"])),
            tuple(json.loads(row["stages_json"])),
            row["cursor"],
            row["status"],
            row["version"],
            row["created_at"],
            row["updated_at"],
            json.loads(row["profile_json"]) if row["profile_json"] else {},
            row["route_reason"],
            row["active_gate"],
            bool(row["cancel_requested"]),
            row["last_error"],
            row["workspace_path"],
        )

    def list_rounds(self, *, limit: int = 100) -> tuple[RoundRecord, ...]:
        safe_limit = max(1, min(int(limit), 1000))
        with self._connect() as conn:
            ids = [
                row[0]
                for row in conn.execute(
                    "SELECT round_id FROM rounds ORDER BY created_at DESC LIMIT ?", (safe_limit,)
                )
            ]
        return tuple(self.get_round(round_id) for round_id in ids)

    def set_status(
        self,
        round_id: str,
        status: str,
        *,
        active_gate: str | None = None,
        last_error: str | None = None,
    ) -> RoundRecord:
        with self._connect() as conn:
            changed = conn.execute(
                """UPDATE rounds
                SET status=?, active_gate=?, last_error=?, version=version+1, updated_at=?
                WHERE round_id=?""",
                (status, active_gate, last_error, _iso(_utcnow()), round_id),
            ).rowcount
        if changed != 1:
            raise KeyError(round_id)
        return self.get_round(round_id)

    def request_cancel(self, round_id: str) -> RoundRecord:
        with self._connect() as conn:
            changed = conn.execute(
                "UPDATE rounds SET cancel_requested=1, updated_at=? WHERE round_id=?",
                (_iso(_utcnow()), round_id),
            ).rowcount
        if changed != 1:
            raise KeyError(round_id)
        return self.get_round(round_id)

    def clear_cancel(self, round_id: str) -> RoundRecord:
        with self._connect() as conn:
            changed = conn.execute(
                "UPDATE rounds SET cancel_requested=0, updated_at=? WHERE round_id=?",
                (_iso(_utcnow()), round_id),
            ).rowcount
        if changed != 1:
            raise KeyError(round_id)
        return self.get_round(round_id)

    def set_workspace_path(self, round_id: str, workspace_path: str) -> RoundRecord:
        with self._connect() as conn:
            changed = conn.execute(
                "UPDATE rounds SET workspace_path=?, updated_at=? WHERE round_id=?",
                (workspace_path, _iso(_utcnow()), round_id),
            ).rowcount
        if changed != 1:
            raise KeyError(round_id)
        return self.get_round(round_id)

    def advance(self, round_id: str, expected_version: int) -> RoundRecord:
        now = _iso(_utcnow())
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT cursor, stages_json, version FROM rounds WHERE round_id = ?", (round_id,)
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                raise KeyError(round_id)
            if row["version"] != expected_version:
                conn.execute("ROLLBACK")
                raise InvalidTransition("stale round version")
            stages = tuple(json.loads(row["stages_json"]))
            cursor = row["cursor"] + 1
            status = "closed" if cursor >= len(stages) else "active"
            conn.execute(
                """UPDATE rounds
                SET cursor=?, status=?, version=version+1, updated_at=?
                WHERE round_id=? AND version=?""",
                (cursor, status, now, round_id, expected_version),
            )
            conn.execute("COMMIT")
        return self.get_round(round_id)

    def jump_to(self, round_id: str, target_stage: str, expected_version: int) -> RoundRecord:
        current = self.get_round(round_id)
        if current.version != expected_version:
            raise InvalidTransition("stale round version")
        try:
            cursor = current.stages.index(target_stage)
        except ValueError as exc:
            raise InvalidTransition(f"unknown target stage: {target_stage}") from exc
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            changed = conn.execute(
                """UPDATE rounds
                SET cursor=?, status='active', version=version+1, updated_at=?
                WHERE round_id=? AND version=?""",
                (cursor, _iso(_utcnow()), round_id, expected_version),
            ).rowcount
            if changed != 1:
                conn.execute("ROLLBACK")
                raise InvalidTransition("concurrent state update")
            conn.execute("COMMIT")
        return self.get_round(round_id)

    def record_event(
        self,
        round_id: str,
        kind: str,
        stage_ref: str | None,
        payload: Mapping[str, Any],
    ) -> EventRecord:
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO stage_events(
                    round_id, stage_ref, kind, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)""",
                (round_id, stage_ref, kind, json.dumps(payload, sort_keys=True), _iso(_utcnow())),
            )
            event_id = int(cursor.lastrowid)
        return self.get_event(event_id)

    def get_event(self, event_id: int) -> EventRecord:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM stage_events WHERE id=?", (event_id,)).fetchone()
        if row is None:
            raise KeyError(event_id)
        return EventRecord(
            row["id"],
            row["round_id"],
            row["stage_ref"],
            row["kind"],
            json.loads(row["payload_json"]),
            row["created_at"],
        )

    def list_events(self, round_id: str, *, after_id: int = 0) -> tuple[EventRecord, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM stage_events WHERE round_id=? AND id>? ORDER BY id",
                (round_id, after_id),
            ).fetchall()
        return tuple(
            EventRecord(
                row["id"],
                row["round_id"],
                row["stage_ref"],
                row["kind"],
                json.loads(row["payload_json"]),
                row["created_at"],
            )
            for row in rows
        )

    def record_artifact(
        self,
        *,
        round_id: str,
        stage_ref: str,
        name: str,
        relative_path: str,
        media_type: str,
        sha256: str,
        size: int,
    ) -> ArtifactRecord:
        created_at = _iso(_utcnow())
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO artifacts(
                    round_id, stage_ref, name, relative_path, media_type, sha256, size, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(round_id, stage_ref, name) DO UPDATE SET
                    relative_path=excluded.relative_path,
                    media_type=excluded.media_type,
                    sha256=excluded.sha256,
                    size=excluded.size,
                    created_at=excluded.created_at""",
                (round_id, stage_ref, name, relative_path, media_type, sha256, size, created_at),
            )
            artifact_id = conn.execute(
                "SELECT id FROM artifacts WHERE round_id=? AND stage_ref=? AND name=?",
                (round_id, stage_ref, name),
            ).fetchone()[0]
        return self.get_artifact(artifact_id)

    def get_artifact(self, artifact_id: int) -> ArtifactRecord:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        return ArtifactRecord(*row)

    def list_artifacts(self, round_id: str) -> tuple[ArtifactRecord, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM artifacts WHERE round_id=? ORDER BY id", (round_id,)
            ).fetchall()
        return tuple(ArtifactRecord(*row) for row in rows)

    def acquire_lease(self, resource_key: str, owner: str, ttl_seconds: int) -> None:
        now, expires = _utcnow(), _utcnow() + timedelta(seconds=ttl_seconds)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT owner, expires_at FROM leases WHERE resource_key=?", (resource_key,)
            ).fetchone()
            if row and datetime.fromisoformat(row["expires_at"]) > now and row["owner"] != owner:
                conn.execute("ROLLBACK")
                raise LeaseUnavailable(f"{resource_key} held by {row['owner']}")
            conn.execute(
                """INSERT INTO leases VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(resource_key) DO UPDATE SET
                    owner=excluded.owner,
                    acquired_at=excluded.acquired_at,
                    heartbeat_at=excluded.heartbeat_at,
                    expires_at=excluded.expires_at""",
                (resource_key, owner, _iso(now), _iso(now), _iso(expires)),
            )
            conn.execute("COMMIT")

    def heartbeat(self, resource_key: str, owner: str, ttl_seconds: int) -> None:
        now = _utcnow()
        expires = now + timedelta(seconds=ttl_seconds)
        with self._connect() as conn:
            changed = conn.execute(
                "UPDATE leases SET heartbeat_at=?, expires_at=? WHERE resource_key=? AND owner=?",
                (_iso(now), _iso(expires), resource_key, owner),
            ).rowcount
        if changed != 1:
            raise LeaseLost(f"lease lost: {resource_key}")

    def release_lease(self, resource_key: str, owner: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM leases WHERE resource_key=? AND owner=?", (resource_key, owner)
            )

    def lease_owner(self, resource_key: str) -> str | None:
        now = _utcnow()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT owner, expires_at FROM leases WHERE resource_key=?", (resource_key,)
            ).fetchone()
        if row is None or datetime.fromisoformat(row["expires_at"]) <= now:
            return None
        return row["owner"]

    def reap_expired_leases(self) -> int:
        with self._connect() as conn:
            return conn.execute(
                "DELETE FROM leases WHERE expires_at <= ?", (_iso(_utcnow()),)
            ).rowcount
