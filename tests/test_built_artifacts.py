"""Fresh built outputs and artifact-bound acceptance, approval and promotion."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import anyio
import pytest
from test_feedback_loop import project
from verification_support import configure_acceptance, git, initialize_verified_repo

from icm_harness.adapters.storage.filesystem import FilesystemEvidenceStore
from icm_harness.evaluation import local_verification_providers, parse_profile, verify_candidate
from icm_harness.kernel.contracts import TaskIntent, TaskProfile
from icm_harness.kernel.providers import EvidenceRef
from icm_harness.workspace import artifact_identity

OUTPUT = ".harness/runtime/product.bin"


def artifact_profile(root):
    initialize_verified_repo(root)
    payload = configure_acceptance(root, f"assert Path('{OUTPUT}').read_bytes() == b'correct'")
    payload["artifact_paths"] = [OUTPUT]
    payload["setup"] = [
        {
            "id": "build",
            "argv": [
                sys.executable,
                "-c",
                f"from pathlib import Path; p=Path('{OUTPUT}'); "
                "p.parent.mkdir(parents=True,exist_ok=True); "
                "p.write_bytes(b'correct')",
            ],
        }
    ]
    return payload


def verify(root, payload):
    return anyio.run(verify_candidate, parse_profile(payload), root, root / ".harness/rounds")


def test_verified_build_is_fresh_and_preserved_as_binary_evidence(tmp_path):
    payload = artifact_profile(tmp_path)
    output = tmp_path / OUTPUT
    output.parent.mkdir(parents=True)
    output.write_bytes(b"stale")
    report = verify(tmp_path, payload)
    assert report["passed"]
    assert report["artifact_digest"] == artifact_identity(tmp_path, (OUTPUT,))
    store = FilesystemEvidenceStore(tmp_path / ".harness/rounds/store")
    assert store.get_blob(EvidenceRef(**report["artifacts"][0]["blob"])) == b"correct"


def test_stale_output_cannot_pass_when_build_produces_nothing(tmp_path):
    payload = artifact_profile(tmp_path)
    payload["setup"] = []
    output = tmp_path / OUTPUT
    output.parent.mkdir(parents=True)
    output.write_bytes(b"correct")
    report = verify(tmp_path, payload)
    assert not report["passed"] and "missing built artifact" in report["error"]


def test_checks_cannot_change_ignored_artifacts_and_certify_them(tmp_path):
    payload = artifact_profile(tmp_path)
    payload["checks"][0]["argv"][-1] += f"; Path('{OUTPUT}').write_bytes(b'changed')"
    report = verify(tmp_path, payload)
    assert not report["passed"] and report["failure_class"] == "artifact_changed"


@pytest.mark.parametrize("produces_attachment", [True, False])
def test_attachments_are_fresh_required_and_preserved(tmp_path, produces_attachment):
    payload = artifact_profile(tmp_path)
    name = ".harness/runtime/screenshot.png"
    payload["checks"][0]["attachments"] = {name: "image/png"}
    output = tmp_path / name
    output.parent.mkdir(parents=True)
    output.write_bytes(b"stale")
    if produces_attachment:
        payload["checks"][0]["argv"][-1] += f"; Path('{name}').write_bytes(b'new screenshot')"
    report = verify(tmp_path, payload)
    assert report["passed"] is produces_attachment
    if produces_attachment:
        store = FilesystemEvidenceStore(tmp_path / ".harness/rounds/store")
        reference = report["commands"][-1]["attachments"][0]["blob"]
        assert reference["media_type"] == "image/png"
        assert store.get_blob(EvidenceRef(**reference)) == b"new screenshot"


def test_artifact_profile_requires_a_store_before_any_command_starts(tmp_path):
    payload = artifact_profile(tmp_path)

    async def scenario():
        return await verify_candidate(
            parse_profile(payload),
            tmp_path,
            tmp_path / ".harness/rounds",
            providers=local_verification_providers(),
        )

    report = anyio.run(scenario)
    assert report["failure_class"] == "unsupported_capability" and not report["commands"]


def test_attachment_cannot_overwrite_a_build_output(tmp_path):
    payload = artifact_profile(tmp_path)
    payload["checks"][0]["attachments"] = {OUTPUT: "application/octet-stream"}
    with pytest.raises(ValueError, match="overwrite"):
        parse_profile(payload)


def test_declared_artifact_cannot_destroy_tracked_product_input(tmp_path):
    payload = artifact_profile(tmp_path)
    output = tmp_path / OUTPUT
    output.parent.mkdir(parents=True)
    output.write_bytes(b"tracked source")
    git(tmp_path, "add", "-f", OUTPUT)
    git(tmp_path, "-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "-m", "tracked")
    report = verify(tmp_path, payload)
    assert not report["passed"] and "tracked product input" in report["error"]
    assert output.read_bytes() == b"tracked source"


def built_round(tmp_path, *, with_attachment=False):
    app, _, _ = project(tmp_path)
    path = tmp_path / ".harness/project.json"
    payload = json.loads(path.read_text())
    payload["artifact_paths"] = [OUTPUT]
    if with_attachment:
        name = ".harness/runtime/approval.png"
        payload["checks"][0]["attachments"] = {name: "image/png"}
        payload["checks"][0]["argv"][-1] += f"; Path('{name}').write_bytes(b'current screenshot')"
    payload["setup"] = [
        {
            "id": "build",
            "argv": [
                sys.executable,
                "-c",
                f"from pathlib import Path; p=Path('{OUTPUT}'); "
                "p.parent.mkdir(parents=True,exist_ok=True); "
                "p.write_bytes(Path('product.txt').read_bytes())",
            ],
        }
    ]
    path.write_text(json.dumps(payload))
    git(tmp_path, "add", ".harness/project.json")
    git(tmp_path, "-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "-m", "build")
    rec = app.create_round(
        TaskProfile(
            "build product",
            intent=TaskIntent.BUILD,
            specification_clarity=0.9,
            epistemic_uncertainty=0.1,
        )
    )
    result = anyio.run(app.run_round, rec.round_id)
    assert result.status == "closed", result.last_error
    return app, rec, result


def test_successful_promotion_records_tested_artifact_identity(tmp_path):
    app, rec, _ = built_round(tmp_path)
    app.approve_promotion(rec.round_id)
    app.promote_round(rec.round_id)
    events = app.events(rec.round_id)
    approved = next(e.payload for e in events if e.kind == "merge_approved")
    promoted = next(e.payload for e in events if e.kind == "round_promoted")
    assert promoted["artifact_digest"] == approved["artifact_digest"]
    assert promoted["verification_run_id"] == approved["run_id"]
    assert (tmp_path / "product.txt").read_text() == "correct"
    assert not (tmp_path / OUTPUT).exists()


def test_corrupted_browser_attachment_blocks_approval(tmp_path):
    app, rec, _ = built_round(tmp_path, with_attachment=True)
    report = [e.payload for e in app.events(rec.round_id) if e.kind == "candidate_verified"][-1]
    digest = report["commands"][-1]["attachments"][0]["blob"]["sha256"]
    path = (
        app.artifacts.round_root
        / rec.round_id
        / "verification/store/blobs"
        / digest[:2]
        / digest[2:]
    )
    path.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="integrity"):
        app.approve_promotion(rec.round_id)


@pytest.mark.parametrize("attack", ["before_approval", "after_approval", "blob"])
def test_artifact_changes_block_delivery_even_when_source_unchanged(tmp_path, attack):
    app, rec, result = built_round(tmp_path)
    if attack == "after_approval":
        app.approve_promotion(rec.round_id)
    if attack == "blob":
        report = [e.payload for e in app.events(rec.round_id) if e.kind == "candidate_verified"][-1]
        digest = report["artifacts"][0]["blob"]["sha256"]
        target = (
            app.artifacts.round_root
            / rec.round_id
            / "verification/store/blobs"
            / digest[:2]
            / digest[2:]
        )
    else:
        target = Path(result.workspace_path) / OUTPUT
    target.write_bytes(b"untested")
    with pytest.raises(ValueError, match="artifact|integrity"):
        (app.promote_round if attack == "after_approval" else app.approve_promotion)(rec.round_id)
    assert not (tmp_path / "product.txt").exists()


@pytest.mark.parametrize("attack", ["source", "duplicate", "symlink", "report", "protected"])
def test_artifact_policy_rejects_unsafe_declarations(tmp_path, attack):
    payload = artifact_profile(tmp_path)
    if attack == "source":
        payload["artifact_paths"] = ["README.md"]
    elif attack == "duplicate":
        payload["artifact_paths"] *= 2
    elif attack == "report":
        payload["checks"][0].update(
            result_format="junit", report=OUTPUT, expected_tests=["fixture::test"]
        )
    elif attack == "protected":
        payload["protected_paths"] = [".harness//runtime/product.bin"]
    else:
        outside = tmp_path / "outside"
        outside.write_bytes(b"source")
        output = tmp_path / OUTPUT
        output.parent.mkdir(parents=True)
        output.symlink_to(outside)
        report = verify(tmp_path, payload)
        assert not report["passed"] and "symlinks" in report["error"]
        assert outside.read_bytes() == b"source"
        return
    with pytest.raises(ValueError):
        parse_profile(payload)
