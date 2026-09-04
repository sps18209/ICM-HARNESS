"""The `.icm/` engine driver and the pointer that links a project's CLAUDE.md to it.

`icm init` writes `.icm/ENGINE.md` (Form B — Claude Code, or any capable coding
agent, drives the ICM loop itself with no external process) and appends a small,
marker-delimited pointer block to the project's `CLAUDE.md` so the agent finds the
engine. Both operations are non-destructive: existing files are never overwritten,
and the pointer is only appended when its marker is absent.
"""
from __future__ import annotations

from pathlib import Path

POINTER_START = "<!-- icm:engine:start -->"
POINTER_END = "<!-- icm:engine:end -->"

POINTER_BLOCK = f"""{POINTER_START}
## ICM structured-work engine

For structured or multi-stage work, read `.icm/ENGINE.md` first. It defines the
cognitive modes, the stage roles and their non-negotiable invariants, and lets you
drive the loop yourself — no external process required. Durable orchestration
(round state, git-worktree isolation, model routing, retries) is available for the
same workspace via the `icm` CLI when you want it.
{POINTER_END}
"""

ENGINE_MD = """# ICM Engine

You are the engine. This file lets a capable coding agent (e.g. Claude Code) run
the ICM production method directly against this workspace — no external `icm`
process required. The workspace *is* the control plane; you read from it and write
back to it.

The `icm` Python CLI can drive this same workspace when you want durable state,
git-worktree isolation, model routing, and bounded retries. This file is the
process it encodes, written so you can execute it yourself.

## 1. On every task: route to a mode

Pick the smallest mode that fits. Compose modes rather than inventing new ones (a
technically uncertain build is `discovery -> build`, not a new monolith).

- **discovery** — unresolved epistemic uncertainty; you must learn before acting.
  Stages: frame -> explore -> research -> adversarial -> synthesis -> validate.
- **build** — a clear, specified change to make.
  Stages: planner -> writer -> tester -> close.
- **decision** — a choice among options with stakes.
  Stages: frame -> evidence -> options -> adversarial -> decide -> validate -> close.
- **review** — understand or audit existing code.
  Stages: ingest -> reconstruct -> inspect -> adversarial -> findings.
- **quick** — trivial, low-risk, well-understood.
  Stages: execute -> verify -> close.

State the chosen route and the reason before you start.

## 2. Walk the stages in order — one role at a time

For each stage:

1. Adopt only that stage's role. Read that stage's contract at
   `1_Modes/<mode>/<NN_stage>/CONTEXT.md` and nothing beyond the budgeted context.
2. Do the stage's work and no later stage's work.
3. Write the stage's output under `1_Modes/<mode>/<NN_stage>/output/` (final,
   user-facing artifacts belong in `5_Artifacts/`).
4. Only then advance. On a substantive defect you may return control to an earlier
   stage **only** if that stage's contract permits it; otherwise stop and report.

## 3. Non-negotiable invariants

- **Planner does not implement. Writer does not redefine. Tester does not repair.**
  Each stage stays in its lane; work assigned to a later stage waits for it.
- **Discovery is separate.** Epistemic work is its own first-class mode, never
  smuggled into a build.
- **Context is pulled in tiers.** Start from the smallest relevant section; escalate
  explicitly and only when needed. "Load the whole repository" is never the move.
- **Mutating work is isolated.** Make product changes on a dedicated git branch or
  worktree, never directly on the base branch. Promotion is a separate, explicit
  step after verification.
- **Durable facts are distinct from round artifacts.** A round's conclusions live in
  `4_Decisions/` and `6_History/`; only *verified* project truth is promoted into
  `0_Context_Wiki/`, with its "Last verified" date and evidence filled in.
- **Stop at human gates.** Where a stage or the task calls for human approval
  (production changes, irreversible or high-stakes actions), stop and ask; do not
  self-approve.

## 4. Where things live (the filesystem is the API)

| Need | Location |
|---|---|
| Verified system facts | `0_Context_Wiki/` |
| Mode + stage contracts | `1_Modes/` |
| Active task / working state | `2_Working_State/` (`CURRENT` names the live round) |
| Claim -> source evidence | `3_Evidence/` |
| Durable decisions | `4_Decisions/` |
| Final generated artifacts | `5_Artifacts/` |
| Closed-round history | `6_History/` |

## 5. Close

A round is done when its mode's final stage is complete, its artifacts are written,
verification has passed, and any human gate has been cleared. Record the outcome in
`4_Decisions/` (and `6_History/` for a closed round). Promote to `0_Context_Wiki/`
only what you have actually verified.
"""


def _has_pointer(text: str) -> bool:
    return POINTER_START in text


def ensure_claude_pointer(target: Path) -> str:
    """Ensure the engine pointer block is present in ``<target>/CLAUDE.md``.

    Returns "created", "appended", or "present". Never overwrites existing content.
    """
    path = target / "CLAUDE.md"
    if not path.exists():
        path.write_text(POINTER_BLOCK, encoding="utf-8")
        return "created"
    existing = path.read_text(encoding="utf-8")
    if _has_pointer(existing):
        return "present"
    separator = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    path.write_text(existing + separator + POINTER_BLOCK, encoding="utf-8")
    return "appended"


def install_engine(target: Path, *, force: bool = False) -> str:
    """Write ``<target>/.icm/ENGINE.md``. Returns "written" or "kept" (already present)."""
    path = target / ".icm" / "ENGINE.md"
    if path.exists() and not force:
        return "kept"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ENGINE_MD, encoding="utf-8")
    return "written"
