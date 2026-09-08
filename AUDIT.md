# ICM Production Harness — ICM self-audit & transform

The harness was run through its own **review → build** method. Review was read-only; the
build stage fixed the two Critical findings — the places where the harness did **not enforce
the discipline it advertises** — and locked them in with tests.

## Audit (review mode)

**Health at intake.** `icm doctor` green, architecture + layout validators pass,
**90 passed / 1 skipped**, ruff clean. Nothing was broken; the findings are
enforcement gaps that the suite couldn't see because it exercised the unwired pieces in
isolation.

**Findings (headline).**

| # | Sev | Finding |
| --- | --- | --- |
| C1 | Critical | Read-only stages weren't contained. review/discovery/decision modes have no `mutates_workspace` stage, so no worktree is created and every stage runs in the **real working tree** (`cwd=workspace`). The Claude adapter denied the write *tools* but left `Bash` under `--permission-mode acceptEdits`, so a shell `>`/`rm` could still mutate the user's files — defeating the "mutations are isolated" invariant. |
| C2 | Critical | No human gate on the merge path. `promote_round` gated only on `status == "closed"`; `build`/`quick` (the modes that mutate + promote) have no gate, and both `icm_run_round` and `icm_promote_round` are callable by the same agent — so an agent could run a build and silently merge it into the base branch. |
| H3 | High | Gate approval was order-insensitive and permanent: `_gate_is_approved` returned true if *any* `gate_approved` event ever existed, so an approval survived `return_to` re-entry and `retry` — a gate approved once was approved forever. |
| H1 | High | `AuthorizationPolicy` is constructed per stage but never read by any adapter (decorative). |
| H2 | High | Intake spawns `subprocess.run(env=os.environ.copy())` (full env, not the adapters' allowlist) and hardcodes the `claude` binary. |

## Transform (build mode) — enforce the discipline

Fixed the two Criticals + the closely-related H3. All existing behavior preserved
(92 passed / 1 skipped after, from 90/1; validators + ruff clean).

- **C1 — contain read-only stages** (`agents/claude_cli.py`). A non-mutating stage now runs
  under `--permission-mode plan` (blocks mutating tool use at the CLI level, the same posture
  pre-round intake uses) instead of `acceptEdits`; the write-tool denial stays as defense in
  depth. A mutating stage still runs under `acceptEdits`.
- **C2 — gate the merge** (`application/service.py`, `mcp/server.py`, `cli/app.py`).
  `promote_round` now refuses unless an explicit `merge_approved` event has been recorded via
  the new `approve_promotion` step — surfaced as `icm approve-merge [--promote]` and the
  `icm_approve_promotion` MCP tool. Promotion is now a deliberate, separately-audited action,
  not an implicit side effect of running.
- **H3 — scope gate approval to the current visit** (`application/service.py`).
  `_gate_is_approved` counts an approval only if it follows the most recent `gate_waiting` for
  that stage, so re-entering a gate (via `return_to` or `retry`) requires fresh approval.

## Cross-repo ports

- **ICM-HARNESS → data-first** (shipped in that repo): the lock/gate/no-clobber discipline
  became data-first's executable `lock` / `verify` / `guard` guardrails.
- **decision-memory-graph → ICM-HARNESS** (proposed, high value): dmg's stdlib-only
  `brier_score` / `expected_calibration_error` are the right tool to close finding **M2**
  (rewards are computed but the learning loop only sees a binary pass/fail). Scoring each
  stage's outcome with a proper calibration score would make `routing/learning.py`
  calibration-aware instead of accuracy-only. dmg's decision-memory graph is also a natural
  backend for the harness's flat SQLite round-event log (institutional memory for `decision`
  mode).

## What still needs a human (documented, not yet fixed)

- **H1** wire `AuthorizationPolicy` into the adapters (translate to `--disallowed-tools` /
  sandbox / network flags) or delete it.
- **H2** reuse the adapter env allowlist for intake and route intake through the configured
  provider.
- **M-series** feed `rewards.reward` + stage `trigger_codes` into the learning/settings path;
  retarget the dead `ContextPromoter` test; offload blocking SQLite off the event loop.

These are larger, behavior-changing refactors best done as their own reviewed rounds.
