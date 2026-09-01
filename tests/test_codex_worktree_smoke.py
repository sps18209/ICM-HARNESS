"""Smoke test: a real Codex CLI driving the harness in an isolated worktree.

This is the one proof the fake-codex tests cannot give — live interaction with
an authenticated `codex` binary against real Git worktree isolation. It is
opt-in and paid, so it only runs when BOTH are true:

    * `codex` is on PATH
    * ICM_SMOKE_CODEX=1

Run it manually with:

    ICM_SMOKE_CODEX=1 python -m pytest tests/test_codex_worktree_smoke.py -v -s
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import anyio
import pytest

from icm_harness.application import HarnessApplication
from icm_harness.config import write_default_config
from icm_harness.kernel.contracts import TaskIntent, TaskProfile

RUN_SMOKE = os.environ.get("ICM_SMOKE_CODEX") == "1" and shutil.which("codex") is not None
SKIP_REASON = "set ICM_SMOKE_CODEX=1 and install an authenticated `codex` to run"


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _initialize_git_workspace(root: Path) -> None:
    (root / "0_Context_Wiki").mkdir(parents=True)
    (root / "2_Working_State").mkdir(parents=True)
    (root / "2_Working_State/CURRENT").write_text("NONE\n", encoding="utf-8")
    write_default_config(root / ".harness/config.toml")
    (root / ".gitignore").write_text(
        ".harness/runtime/\n.harness/worktrees/\n", encoding="utf-8"
    )
    (root / "README.md").write_text("# smoke target\n", encoding="utf-8")
    _git(root, "init")
    _git(root, "add", ".")
    _git(
        root,
        "-c",
        "user.name=ICM Smoke",
        "-c",
        "user.email=smoke@example.com",
        "commit",
        "-m",
        "base",
    )


@pytest.mark.skipif(not RUN_SMOKE, reason=SKIP_REASON)
def test_real_codex_runs_in_isolated_worktree(tmp_path):
    _initialize_git_workspace(tmp_path)

    # Default config → provider=codex-cli, workspace.strategy=worktree.
    app = HarnessApplication(tmp_path)
    profile = TaskProfile(
        "Add a one-line CONTRIBUTING.md that says how to run the tests.",
        intent=TaskIntent.QUICK,
        specification_clarity=0.9,
        epistemic_uncertainty=0.1,
        stakes=0.2,
        reversibility=0.9,
        production_change_required=True,
    )
    created = app.create_round(profile)
    result = anyio.run(app.run_round, created.round_id)

    events = app.events(created.round_id)
    kinds = {event.kind for event in events}

    # The harness must have actually invoked the agent (not just created a round).
    assert "stage_started" in kinds, "no stage was started"
    assert result.status in {"closed", "waiting_approval", "failed", "blocked"}

    # Any mutation must have been isolated to a per-round worktree, never the base.
    latest = app.get_round(created.round_id)
    if latest.workspace_path:
        worktree = Path(latest.workspace_path)
        assert worktree != tmp_path
        assert worktree.exists()

    # Whatever the agent produced should be visible as a diff and/or artifacts.
    diff = app.diff_round(created.round_id)
    artifacts = app.list_artifacts(created.round_id)
    assert diff or artifacts, "real agent produced neither a diff nor artifacts"

    # If it completed, promotion must be an explicit, clean merge.
    if result.status == "closed" and latest.workspace_path:
        app.promote_round(created.round_id)
        assert any(event.kind == "round_promoted" for event in app.events(created.round_id))
