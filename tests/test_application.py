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

    app.promote_round(created.round_id)
    assert (tmp_path / "produced.txt").read_text() == "isolated\n"
    assert any(event.kind == "round_promoted" for event in app.events(created.round_id))
