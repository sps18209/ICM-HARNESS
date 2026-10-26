"""Content-addressed binary evidence and immutable per-run receipt files.

Integrity under the operator's account, not an attestation against that account.
The existing application event store remains the append-only metadata index.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from contextlib import suppress
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from icm_harness.kernel.providers import EvidenceRef


class FilesystemEvidenceStore:
    def __init__(self, root: str | Path, *, max_blob_bytes: int = 32 * 1024 * 1024):
        if type(max_blob_bytes) is not int or max_blob_bytes <= 0:
            raise ValueError("blob budget must be a positive integer")
        self.root = Path(root).resolve()
        self.max_blob_bytes = max_blob_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    def _inside(self, relative: str) -> Path:
        path = self.root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ValueError("evidence path escapes store or uses a symlink")
        return path

    def _blob(self, digest: str) -> Path:
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("invalid evidence digest")
        return self._inside(f"blobs/{digest[:2]}/{digest[2:]}")

    def put_blob(self, source: bytes, media_type: str) -> EvidenceRef:
        if not isinstance(source, bytes) or len(source) > self.max_blob_bytes:
            raise ValueError("evidence must be bytes within the configured blob budget")
        if not isinstance(media_type, str) or not media_type.strip():
            raise ValueError("evidence requires a media type")
        reference = EvidenceRef(sha256(source).hexdigest(), len(source), media_type)
        destination = self._blob(reference.sha256)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(source)
                stream.flush()
                os.fsync(stream.fileno())
            with suppress(FileExistsError):
                # Atomic create without overwriting a concurrently stored blob.
                os.link(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self.get_blob(reference)
        return reference

    def get_blob(self, reference: EvidenceRef) -> bytes:
        path = self._blob(reference.sha256)
        if path.stat().st_size > self.max_blob_bytes:
            raise ValueError("stored evidence exceeds blob budget")
        with path.open("rb") as stream:
            source = stream.read(self.max_blob_bytes + 1)
        if len(source) != reference.size or sha256(source).hexdigest() != reference.sha256:
            raise ValueError("evidence integrity check failed")
        return source

    def seal_run(self, run_id: str, manifest: bytes) -> EvidenceRef:
        if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", run_id):
            raise ValueError("invalid evidence run ID")
        if not isinstance(json.loads(manifest), dict):
            raise ValueError("verification snapshot must be a JSON object")
        reference = self.put_blob(manifest, "application/json")
        destination = self._inside(f"runs/{run_id}.json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(reference), sort_keys=True).encode()
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return reference
