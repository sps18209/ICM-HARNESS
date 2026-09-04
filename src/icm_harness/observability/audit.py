import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from icm_harness.workspace import file_lock


@dataclass(frozen=True, slots=True)
class AuditEvent:
    kind: str
    round_id: str
    stage_ref: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class JsonlAuditSink:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = self.path.with_suffix(self.path.suffix + ".lock")

    def emit(self, event: AuditEvent) -> None:
        line = json.dumps(asdict(event), sort_keys=True)
        with file_lock(self.lock), self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
