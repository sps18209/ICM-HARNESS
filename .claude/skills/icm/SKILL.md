---
name: icm
description: >-
  Run structured, high-stakes, or multi-step work through the ICM production
  method — mode routing (discovery / build / decision / review / quick), one
  role per stage with hard invariants, isolated mutations, and human approval
  gates. Use this whenever the user wants disciplined execution rather than a
  quick edit: shipping a non-trivial feature or refactor, weighing a
  reversible-or-not decision, auditing or reviewing code, or researching
  something uncertain before acting — and especially when they say "run this as
  a round", "use the ICM harness", "/icm", "be disciplined about this", "plan
  then build then verify", or want checkpoints before anything lands. Prefer the
  real `icm` CLI or `icm_*` MCP tools when present; otherwise carry the method
  yourself. This skill GUIDES the work and never takes over: it never scaffolds
  files at the repo root, never overwrites the user's files, keeps its own state
  under `.icm/`, and stops for the user's approval before landing anything.
---

# ICM — the production method as a tool you call

You are the driver. This skill is something you *invoke* when a task deserves
discipline; it guides the work and then steps back. It is not a framework you
live inside, and it must never behave like one.

The ICM method separates concerns that a single loop usually collapses: which
mode of thinking the task needs, one role at a time, mutations kept isolated
until a human approves, and a clean record of what happened. Follow it when the
stakes or the uncertainty make "just edit the file" the wrong move.

## Ground rules — these are what keep it a guide, not a takeover

Hold these on every task, before anything else:

- **No root-level scatter.** Never create working files or folders at the
  project root. Everything this method needs for its own bookkeeping lives under
  a single `.icm/` directory (create it lazily, only if you actually need it).
  The user's repository layout is theirs; you are a guest in it.
- **Never overwrite the user's files.** A file that already exists is not yours
  to clobber. Add to the user's own files only by invitation, and then only by
  *appending* a small, clearly-marked block — never by replacing content. If
  something you'd write already exists, leave it and say so.
- **Isolate mutations.** Product changes go on a dedicated git branch or
  worktree, never straight onto the working tree or the base branch. The user
  promotes them; you don't land them silently.
- **Stop at human gates.** For anything irreversible, production-affecting, or
  high-stakes, show the diff and wait for an explicit yes. Never self-approve.
- **Pull context in tiers.** Start from the smallest relevant slice and escalate
  only when you must. "Load the whole repository" is never the move.

If honoring these ever conflicts with finishing faster, honor these.

## First: use the real engine if it's here

The harness may already be installed. Prefer driving it over reimplementing it —
that keeps durable state, git-worktree isolation, model routing, and bounded
retries that you don't get for free.

- **MCP tools** (names beginning `icm_`): if you can see `icm_create_round`,
  `icm_run_round`, `icm_get_round`, `icm_diff`, `icm_approve_gate`,
  `icm_promote_round`, `icm_events`, `icm_artifacts`, `icm_list_rounds`,
  `icm_cancel_round`, `icm_retry_round` — use them. Create a round for the
  objective, run it, read the diff, pause at `icm_approve_gate`, and land it only
  when the user approves via `icm_promote_round`. This is the method as a
  sequence of tool calls, with you in charge between them.
- **CLI**: if `icm` is on `PATH` (check with `icm doctor`), the same flow is
  `icm new "objective" --run` → `icm status` / `icm diff` → `icm approve` →
  `icm promote`. Start in `icm-dry on` for a safe dry run when unsure.

**Auto-install when the source is right here.** If `icm` is not on `PATH` but the
harness *source* is available without touching the user's project, install it into
the session and use the CLI. It is available when either of these exists:

- this repo **is** the harness — a `pyproject.toml` naming `icm-production-harness`
  at the repo root (in the harness's own repo a SessionStart hook already does this
  for you on Claude Code on the web); or
- a `harness/` folder sits next to this skill (the packaged `.skill` bundle).

Then, once, from that location:

```bash
python3 -m pip install -e .        # or: pip install -e harness
icm doctor                         # confirm the CLI is live
```

Do **not** run `pip install` of the harness into an unrelated user project, and
never scaffold harness files across their repo root to get the engine. If no
installable source is present, carry the method yourself, as below — self-driving
needs nothing but this file.

## Route the task to the smallest mode that fits

State the mode and the reason before you start. Compose modes rather than
inventing new ones (a technically uncertain build is `discovery -> build`).

- **discovery** — you must learn before you can act (unresolved uncertainty).
  Stages: frame -> explore -> research -> adversarial -> synthesis -> validate.
- **build** — a clear, specified change to make.
  Stages: planner -> writer -> tester -> close.
- **decision** — a choice among options with real stakes.
  Stages: frame -> evidence -> options -> adversarial -> decide -> validate -> close.
- **review** — understand or audit existing code.
  Stages: ingest -> reconstruct -> inspect -> adversarial -> findings.
- **quick** — trivial, low-risk, well-understood.
  Stages: execute -> verify -> close.

## Walk the stages, one role at a time

For each stage: adopt only that stage's role, do that stage's work and no
later stage's, then advance. The role boundaries are the point — they are why
the output is trustworthy:

- **Planner plans; it does not implement.** A plan that starts editing code has
  stopped being a plan.
- **Writer implements the approved plan; it does not redefine it.** If the plan
  is wrong, return to the planner — don't quietly rewrite the intent.
- **Tester verifies; it does not repair.** A tester that patches the code to make
  its own check pass has destroyed the signal. Report the failure back instead.
- **Discovery is its own mode**, never smuggled into a build. Epistemic work and
  construction work want different postures; keep them apart.

On a substantive defect you may hand control back to an earlier stage only when
that makes sense for the mode; otherwise stop and report rather than pressing on.

## Keep a light record, under `.icm/`

If the task benefits from a trail, keep stage notes and artifacts under
`.icm/rounds/<id>/` — never at the repo root. Durable, verified project facts
are different from a round's working notes: propose promoting a fact into the
project's own knowledge only once it's verified, and only where the project
already keeps such things. When in doubt, leave the user's tree untouched and
summarize in chat.

## Close

A task is done when its mode's final stage is complete, the work is verified, any
human gate has been cleared, and — for mutating work — the isolated branch is
ready for the user to promote. Say plainly what was done, what was checked, and
what still needs a human. Then step back: you were called to guide this, not to
own it.
