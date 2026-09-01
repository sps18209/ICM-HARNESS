import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: str
    round_id: str
    stage_ref: str
    owner: str
    status: str
    attempt: int
    max_attempts: int
    deadline_at: str
    heartbeat_at: str
    last_error: str | None


class SQLiteRunStore:
    TERMINAL = frozenset({"passed", "failed", "cancelled", "dead_letter"})

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                round_id TEXT NOT NULL,
                stage_ref TEXT NOT NULL,
                owner TEXT NOT NULL,
                status TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                max_attempts INTEGER NOT NULL,
                deadline_at TEXT NOT NULL,
                heartbeat_at TEXT NOT NULL,
                last_error TEXT
            )
            """)

    def start(
        self,
        round_id: str,
        stage_ref: str,
        owner: str,
        deadline_at: str,
        max_attempts: int = 3,
        attempt: int = 1,
    ) -> RunRecord:
        run_id = f"run-{uuid.uuid4().hex[:16]}"
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?, NULL)",
                (run_id, round_id, stage_ref, owner, attempt, max_attempts, deadline_at, _now()),
            )
        return self.get(run_id)

    def get(self, run_id: str) -> RunRecord:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            raise KeyError(run_id)
        return RunRecord(*row)

    def heartbeat(self, run_id: str, owner: str) -> None:
        with sqlite3.connect(self.path) as conn:
            changed = conn.execute(
                "UPDATE runs SET heartbeat_at=? WHERE run_id=? AND owner=? AND status='running'",
                (_now(), run_id, owner),
            ).rowcount
        if changed != 1:
            raise RuntimeError(f"run is no longer owned/running: {run_id}")

    def finish(self, run_id: str, status: str, error: str | None = None) -> RunRecord:
        if status not in self.TERMINAL:
            raise ValueError(f"invalid terminal status: {status}")
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "UPDATE runs SET status=?, last_error=?, heartbeat_at=? WHERE run_id=?",
                (status, error, _now(), run_id),
            )
        return self.get(run_id)

    def recover_expired(self, now_iso: str) -> tuple[RunRecord, ...]:
        """Move expired running attempts to failed/dead-letter deterministically."""
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                "SELECT run_id FROM runs WHERE status='running' AND deadline_at <= ?",
                (now_iso,),
            ).fetchall()
        changed = []
        for (run_id,) in rows:
            rec = self.get(run_id)
            target = "dead_letter" if rec.attempt >= rec.max_attempts else "failed"
            changed.append(self.finish(run_id, target, "stage deadline exceeded"))
        return tuple(changed)
