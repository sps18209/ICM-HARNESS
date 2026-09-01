import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    namespace: str
    key: str
    value: str
    verified: bool
    updated_at: str


class SQLiteMemoryStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS memory (
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                verified INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(namespace, key)
            )
            """)

    def put(self, namespace: str, key: str, value: str, *, verified: bool = False) -> None:
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
            INSERT INTO memory(namespace,key,value,verified,updated_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(namespace,key) DO UPDATE SET
            value=excluded.value,verified=excluded.verified,updated_at=excluded.updated_at
            """,
                (namespace, key, value, int(verified), now),
            )

    def get(self, namespace: str, key: str) -> MemoryRecord | None:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                """SELECT namespace, key, value, verified, updated_at
                FROM memory WHERE namespace=? AND key=?""",
                (namespace, key),
            ).fetchone()
        return None if row is None else MemoryRecord(row[0], row[1], row[2], bool(row[3]), row[4])
