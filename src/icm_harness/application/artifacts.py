from __future__ import annotations

import json
import mimetypes
import os
import tempfile
from hashlib import sha256
from pathlib import Path

from icm_harness.kernel.state import ArtifactRecord, SQLiteStateStore

MAX_ARTIFACT_BYTES = 10 * 1024 * 1024


class ArtifactStore:
    def __init__(self, root: str | Path, state: SQLiteStateStore):
        self.root = Path(root).resolve()
        self.state = state
        self.round_root = self.root / ".harness/rounds"

    def stage_dir(self, round_id: str, stage_ref: str) -> Path:
        if not round_id.startswith("r-") or any(
            part in {".", ".."} for part in Path(round_id).parts
        ):
            raise ValueError(f"invalid round id: {round_id}")
        if not stage_ref or any(
            char not in "abcdefghijklmnopqrstuvwxyz0123456789-_." for char in stage_ref
        ):
            raise ValueError(f"invalid stage ref: {stage_ref}")
        path = self.round_root / round_id / "stages" / stage_ref
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_many(
        self,
        round_id: str,
        stage_ref: str,
        artifacts: dict[str, str] | object,
    ) -> tuple[ArtifactRecord, ...]:
        if not isinstance(artifacts, dict):
            artifacts = dict(artifacts)
        destination = self.stage_dir(round_id, stage_ref)
        written = []
        for name, content in artifacts.items():
            if Path(name).name != name or name in {".", ".."}:
                raise ValueError(f"artifact name must be a filename: {name}")
            if not isinstance(content, str):
                raise TypeError(f"artifact content must be text: {name}")
            data = content.encode("utf-8")
            if len(data) > MAX_ARTIFACT_BYTES:
                raise ValueError(f"artifact exceeds {MAX_ARTIFACT_BYTES} bytes: {name}")
            if name.endswith(".json"):
                json.loads(content)
            target = destination / name
            with tempfile.NamedTemporaryFile(dir=destination, delete=False) as handle:
                handle.write(data)
                temporary = Path(handle.name)
            os.replace(temporary, target)
            relative = target.relative_to(self.root).as_posix()
            media_type = mimetypes.guess_type(name)[0] or "text/plain"
            written.append(
                self.state.record_artifact(
                    round_id=round_id,
                    stage_ref=stage_ref,
                    name=name,
                    relative_path=relative,
                    media_type=media_type,
                    sha256=sha256(data).hexdigest(),
                    size=len(data),
                )
            )
        return tuple(written)

    def read(self, artifact: ArtifactRecord) -> str:
        target = (self.root / artifact.relative_path).resolve()
        allowed = self.round_root.resolve()
        if target != allowed and allowed not in target.parents:
            raise ValueError("artifact path escapes the round store")
        data = target.read_bytes()
        if sha256(data).hexdigest() != artifact.sha256:
            raise ValueError(f"artifact integrity check failed: {artifact.name}")
        return data.decode("utf-8", errors="replace")
