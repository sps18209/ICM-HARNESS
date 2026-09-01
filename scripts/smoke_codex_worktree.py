#!/usr/bin/env python3
"""Manual smoke run: drive a real Codex CLI through the harness in a Git worktree.

Unlike the fake-codex tests, this exercises live interaction with an
authenticated `codex` binary and real worktree isolation. It creates a
throwaway Git repo, runs one QUICK round with the default (codex-cli) provider,
prints the event trail, diff, and artifacts, and reports whether the round
completed and could be promoted.

Usage:
    python scripts/smoke_codex_worktree.py [objective]

Requires `codex` on PATH and valid Codex authentication. This makes real,
possibly paid, model calls.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import anyio

from icm_harness.application import HarnessApplication
from icm_harness.config import write_default_config
from icm_harness.kernel.contracts import TaskIntent, TaskProfile

DEFAULT_OBJECTIVE = "Add a one-line CONTRIBUTING.md describing how to run the tests."


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


def _init(root: Path) -> None:
    (root / "0_Context_Wiki").mkdir(parents=True)
    (root / "2_Working_State").mkdir(parents=True)
    (root / "2_Working_State/CURRENT").write_text("NONE\n", encoding="utf-8")
    write_default_config(root / ".harness/config.toml")
    (root / ".gitignore").write_text(".harness/runtime/\n.harness/worktrees/\n", encoding="utf-8")
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


def main(argv: list[str]) -> int:
    if shutil.which("codex") is None:
        print("codex is not on PATH; install and authenticate it first.", file=sys.stderr)
        return 2

    objective = argv[1] if len(argv) > 1 else DEFAULT_OBJECTIVE
    root = Path(tempfile.mkdtemp(prefix="icm-smoke-"))
    print(f"workspace: {root}")
    _init(root)

    app = HarnessApplication(root)
    profile = TaskProfile(
        objective,
        intent=TaskIntent.QUICK,
        specification_clarity=0.9,
        epistemic_uncertainty=0.1,
        stakes=0.2,
        reversibility=0.9,
        production_change_required=True,
    )
    created = app.create_round(profile)
    print(f"round: {created.round_id}  route: {' -> '.join(created.route)}")

    result = anyio.run(app.run_round, created.round_id)
    print(f"\nfinal status: {result.status}")
    if result.last_error:
        print(f"last error: {result.last_error}")

    print("\n--- events ---")
    for event in app.events(created.round_id):
        stage = f" [{event.stage_ref}]" if event.stage_ref else ""
        print(f"  #{event.id}{stage} {event.kind}")

    latest = app.get_round(created.round_id)
    if latest.workspace_path:
        print(f"\nworktree: {latest.workspace_path}")
    print("\n--- artifacts ---")
    for artifact in app.list_artifacts(created.round_id):
        print(f"  {artifact.name} ({artifact.size}B) [{artifact.stage_ref}]")

    diff = app.diff_round(created.round_id)
    print("\n--- worktree diff ---")
    print(diff or "(empty)")

    if result.status == "closed" and latest.workspace_path:
        app.promote_round(created.round_id)
        print("\npromoted round into base branch.")

    print(f"\nInspect or remove the workspace at: {root}")
    return 0 if result.status in {"closed", "waiting_approval"} else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
