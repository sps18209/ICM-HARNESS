from __future__ import annotations

import json
import subprocess
from pathlib import Path

import anyio

from icm_harness.agents.contracts import StageInvocation
from icm_harness.application import HarnessApplication
from icm_harness.config import write_default_config
from icm_harness.kernel.contracts import StageResult, StageStatus, TaskIntent, TaskProfile


def initialize(root: Path) -> None:
    (root / "0_Context_Wiki").mkdir(parents=True)
    (root / "2_Working_State").mkdir(parents=True)
    (root / "2_Working_State/CURRENT").write_text("NONE\n", encoding="utf-8")
    write_default_config(root / ".harness/config.toml")


def build_profile(objective="ship the feature"):
    return TaskProfile(
        objective,
        intent=TaskIntent.BUILD,
        specification_clarity=0.9,
        epistemic_uncertainty=0.1,
        stakes=0.4,
        reversibility=0.8,
        production_change_required=True,
    )


def test_dry_run_executes_a_complete_build_round(tmp_path):
    initialize(tmp_path)
    app = HarnessApplication(tmp_path, dry_run=True)
    created = app.create_round(build_profile())
    result = anyio.run(app.run_round, created.round_id)

    assert result.status == "closed"
    assert result.current_stage is None
    assert [artifact.name for artifact in app.list_artifacts(result.round_id)] == [
        "execution-plan.md",
        "context-manifest.json",
        "change-manifest.json",
        "implementation-notes.md",
        "test-report.json",
        "final-record.md",
    ]
    assert any(event.kind == "round_completed" for event in app.events(result.round_id))
    assert app.current_round() is None


def test_decision_round_pauses_at_and_resumes_from_human_gate(tmp_path):
    initialize(tmp_path)
    app = HarnessApplication(tmp_path, dry_run=True)
    created = app.create_round(TaskProfile("choose a migration", intent=TaskIntent.DECIDE))

    waiting = anyio.run(app.run_round, created.round_id)
    assert waiting.status == "waiting_approval"
    assert waiting.current_stage == "decision.decide"
    assert waiting.active_gate == "decision.decide"

    app.approve_round(created.round_id)
    completed = anyio.run(app.run_round, created.round_id)
    assert completed.status == "closed"
    assert len(app.list_artifacts(created.round_id)) == 7


def test_gate_approval_is_scoped_to_the_current_visit(tmp_path):
    # H3: an approval recorded for one visit must not auto-satisfy a later re-entry of the
    # same gate. Approval counts only when it follows the most recent gate_waiting.
    initialize(tmp_path)
    app = HarnessApplication(tmp_path, dry_run=True)
    created = app.create_round(TaskProfile("choose a migration", intent=TaskIntent.DECIDE))
    gate = "decision.decide"
    rid = created.round_id

    assert app._gate_is_approved(rid, gate) is False
    app._event(rid, "gate_waiting", gate, {})
    assert app._gate_is_approved(rid, gate) is False
    app._event(rid, "gate_approved", gate, {"stage": gate})
    assert app._gate_is_approved(rid, gate) is True
    # Re-entry: a fresh gate_waiting revokes the stale approval until re-approved.
    app._event(rid, "gate_waiting", gate, {})
    assert app._gate_is_approved(rid, gate) is False
    app._event(rid, "gate_approved", gate, {"stage": gate})
    assert app._gate_is_approved(rid, gate) is True


def test_approve_promotion_requires_a_closed_round(tmp_path):
    import pytest

    initialize(tmp_path)
    app = HarnessApplication(tmp_path, dry_run=True)
    created = app.create_round(build_profile())  # active, not closed
    with pytest.raises(ValueError, match="must be closed"):
        app.approve_promotion(created.round_id)


class EmptyAgent:
    async def run(self, invocation: StageInvocation) -> StageResult:
        return StageResult(StageStatus.PASS, "claimed success without artifacts")


def test_required_artifact_gate_fails_closed_after_bounded_attempts(tmp_path):
    initialize(tmp_path)
    app = HarnessApplication(tmp_path, agent=EmptyAgent(), dry_run=True)
    created = app.create_round(build_profile())
    result = anyio.run(app.run_round, created.round_id)

    assert result.status == "failed"
    failures = [
        event for event in app.events(created.round_id) if event.kind == "stage_attempt_failed"
    ]
    assert len(failures) == app.config.runtime.max_attempts
    assert "missing required outputs" in (result.last_error or "")


class WorktreeAgent:
    async def run(self, invocation: StageInvocation) -> StageResult:
        if invocation.stage.ref == "build.writer":
            (invocation.workspace / "produced.txt").write_text("isolated\n", encoding="utf-8")
        artifacts = {}
        for name in invocation.stage.required_outputs:
            if name.endswith(".json"):
                artifacts[name] = json.dumps({"stage": invocation.stage.ref})
            else:
                artifacts[name] = f"# {invocation.stage.ref}\n"
        return StageResult(StageStatus.PASS, "complete", artifacts=artifacts)


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


def test_mutation_is_isolated_until_explicit_promotion(tmp_path):
    initialize(tmp_path)
    (tmp_path / ".gitignore").write_text(
        ".harness/runtime/\n.harness/worktrees/\n", encoding="utf-8"
    )
    (tmp_path / "base.txt").write_text("base\n", encoding="utf-8")
    git(tmp_path, "init")
    git(tmp_path, "add", ".gitignore", "base.txt")
    git(
        tmp_path,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "base",
    )

    app = HarnessApplication(tmp_path, agent=WorktreeAgent())
    created = app.create_round(build_profile())
    completed = anyio.run(app.run_round, created.round_id)

    assert completed.status == "closed"
    assert completed.workspace_path is not None
    assert not (tmp_path / "produced.txt").exists()
    assert (Path(completed.workspace_path) / "produced.txt").read_text() == "isolated\n"
    assert "produced.txt" in app.diff_round(created.round_id)

    # C2: promotion is a human gate, not an implicit side effect of running. It must refuse
    # to merge until promotion is explicitly approved.
    import pytest

    with pytest.raises(ValueError, match="requires explicit promotion approval"):
        app.promote_round(created.round_id)
    assert not (tmp_path / "produced.txt").exists()  # still isolated

    app.approve_promotion(created.round_id)
    app.promote_round(created.round_id)
    assert (tmp_path / "produced.txt").read_text() == "isolated\n"
    assert any(event.kind == "merge_approved" for event in app.events(created.round_id))
    assert any(event.kind == "round_promoted" for event in app.events(created.round_id))


def test_advisory_jev_reviews_grade_stages_and_promotion_without_gating(tmp_path, monkeypatch):
    """typesafe-jev.md points 2 & 3: reviews are recorded as events, degrade to
    an *_unavailable event on adapter failure, and never block the round."""
    from icm_harness.integrations.typesafe import DiffReview, StageReview

    initialize(tmp_path)
    config_path = tmp_path / ".harness/config.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        .replace('semantic_gate = "none"', 'semantic_gate = "typesafe"')
        .replace('promotion_review = "none"', 'promotion_review = "typesafe"'),
        encoding="utf-8",
    )
    (tmp_path / ".gitignore").write_text(
        ".harness/runtime/\n.harness/worktrees/\n", encoding="utf-8"
    )
    (tmp_path / "base.txt").write_text("base\n", encoding="utf-8")
    git(tmp_path, "init")
    git(tmp_path, "add", ".gitignore", "base.txt")
    git(tmp_path, "-c", "user.name=T", "-c", "user.email=t@e.c", "commit", "-m", "base")

    def fake_stage_review(objective, stage_ref, outputs, **kwargs):
        if stage_ref == "build.writer":
            raise RuntimeError("api down")
        return StageReview(addresses_objective=0.9, claims_verified=0.4, quality=0.8)

    def fake_diff_review(objective, diff, **kwargs):
        assert "produced.txt" in diff
        return DiffReview(
            consistent_with_objective=0.9,
            touches_production_config=0.8,
            removes_tests=0.0,
            exposes_secrets=0.0,
        )

    monkeypatch.setattr(
        "icm_harness.integrations.typesafe.review_stage_outputs", fake_stage_review
    )
    monkeypatch.setattr("icm_harness.integrations.typesafe.review_diff", fake_diff_review)

    app = HarnessApplication(tmp_path, agent=WorktreeAgent())
    created = app.create_round(build_profile())
    completed = anyio.run(app.run_round, created.round_id)
    assert completed.status == "closed"  # the failing reviewer never blocked anything

    events = app.events(created.round_id)
    graded = [e for e in events if e.kind == "semantic_gate"]
    degraded = [e for e in events if e.kind == "semantic_gate_unavailable"]
    assert graded and all(
        "verification claims may be unsubstantiated" in e.payload["concerns"] for e in graded
    )
    assert [e.stage_ref for e in degraded] == ["build.writer"]

    app.approve_promotion(created.round_id)
    events = app.events(created.round_id)
    (reviewed,) = [e for e in events if e.kind == "promotion_reviewed"]
    assert reviewed.payload["suggested_approval_class"] == "external_action"
    assert "production or deployment configuration" in reviewed.payload["concerns"][0]
    # the review is advisory: approval was still recorded and promotion works
    assert any(e.kind == "merge_approved" for e in events)
    app.promote_round(created.round_id)
    assert (tmp_path / "produced.txt").exists()
