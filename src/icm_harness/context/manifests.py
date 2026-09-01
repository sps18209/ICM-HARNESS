from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    source: str
    selector: str
    reason: str
    required: bool = False
    tier: int = 1


@dataclass(frozen=True, slots=True)
class ContextManifest:
    stage_ref: str
    entries: tuple[ManifestEntry, ...]
    version: int = 1

    def write(self, path: str | Path) -> None:
        payload = {
            "version": self.version,
            "stage_ref": self.stage_ref,
            "entries": [asdict(x) for x in self.entries],
        }
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    @classmethod
    def read(cls, path: str | Path) -> ContextManifest:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            data["stage_ref"],
            tuple(ManifestEntry(**entry) for entry in data["entries"]),
            data.get("version", 1),
        )
