"""Binary evidence integrity and preservation of authoritative verification snapshots."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from icm_harness.adapters.storage.filesystem import FilesystemEvidenceStore
from icm_harness.kernel.providers import EvidenceRef


def test_binary_blobs_are_content_addressed_deduplicated_and_checked(tmp_path):
    store = FilesystemEvidenceStore(tmp_path)
    payload = b"\x89PNG\x00\xffsynthetic-binary-fixture"
    reference = store.put_blob(payload, "image/png")
    assert store.put_blob(payload, "image/png") == reference
    assert store.get_blob(reference) == payload
    blobs = list((tmp_path / "blobs").glob("*/*"))
    assert len(blobs) == 1
    blobs[0].write_bytes(b"tampered")
    with pytest.raises(ValueError, match="integrity"):
        store.get_blob(reference)
    with pytest.raises(ValueError, match="integrity"):
        store.put_blob(payload, "image/png")


def test_sealed_run_cannot_be_replaced(tmp_path):
    store = FilesystemEvidenceStore(tmp_path)
    reference = store.seal_run("verify-fixture", b'{"passed":true}')
    with pytest.raises(FileExistsError):
        store.seal_run("verify-fixture", b'{"passed":false}')
    receipt = json.loads((tmp_path / "runs/verify-fixture.json").read_text())
    assert receipt["sha256"] == reference.sha256
    assert json.loads(store.get_blob(reference))["passed"]


@pytest.mark.parametrize("attack", ["digest", "size", "symlink", "budget"])
def test_evidence_references_cannot_escape_or_hide_changes(tmp_path, attack):
    store = FilesystemEvidenceStore(tmp_path / "store", max_blob_bytes=100)
    reference = store.put_blob(b"original", "application/octet-stream")
    if attack == "digest":
        reference = EvidenceRef("../../outside", 8, "text/plain")
    elif attack == "size":
        reference = replace(reference, size=1)
    elif attack == "symlink":
        path = next((tmp_path / "store/blobs").glob("*/*"))
        outside = tmp_path / "outside"
        outside.write_bytes(b"original")
        path.unlink()
        path.symlink_to(outside)
    else:
        with pytest.raises(ValueError, match="budget"):
            store.put_blob(b"x" * 101, "text/plain")
        return
    with pytest.raises(ValueError):
        store.get_blob(reference)
