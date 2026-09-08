# ADR-0010: Harvest BAO write-scope and approval classes; reject wholesale kit adoption

Status: Accepted

## Context

A "Gstack × Bounded Agent Organization (BAO) hybrid kit" was proposed for
integration. It ships gated delivery stages, eight agent personas, a `team.yaml`
roster, six JSON schemas, a `CLAUDE.md` template, and an approval-class taxonomy.

Roughly 80% of the kit restates what this harness already is: gated modes
(ADR-0002), one-role-per-stage separation (ADR-0003), mutation isolation
(ADR-0005), pull-based context (ADR-0004), evidence-before-completion, and human
gates. Adopting the kit whole would stand up a second, competing control plane
(its own roster, personas, and lifecycle docs) that duplicates and dilutes ours.

Two BAO ideas are expressed more sharply in the kit than anywhere in the harness
and are additive rather than duplicative:

1. **Per-role least-privilege write scope** (`allowed_paths`). Our invariants say
   *who* may act and isolate *where* concurrent writers run (worktrees), but no
   contract bounds *which paths* a given role may modify.
2. **A named approval-class taxonomy** — `local_reversible`, `project_scope`,
   `external_action`, `destructive`, `security_sensitive`. Our gate model
   (`policies/risk.py`, `policies/authorization.py`) computes *whether* a human
   gate is needed but lacks a legible vocabulary for *why*.

## Decision

Do not adopt the kit. Harvest exactly two concepts as native `policies`
submodules, consistent with the existing barrel/adapter architecture:

- `policies/write_scope.py` — a role's declared `allowed_paths` (glob allow-list,
  optional `denied_paths`), and a pure check that a set of changed paths stays in
  scope. Complements worktree isolation; it does not replace it.
- `policies/approval.py` — the five approval classes, which require a human gate,
  and a classifier from an intended action to its class.

Both ship as small, tested, frozen-dataclass policies exported through the
`policies` barrel. They are drafted as standalone policy primitives; wiring them
into the execution/gate path is deliberately left to a follow-up so this change
stays reviewable and reversible.

Explicitly rejected from the kit: the persona files, `team.yaml` roster,
`TEAM.md`, `CLAUDE.md.template`, and the `run-manifest` / `team-contract`
schemas — all redundant with existing harness structure. The JSON handoff/audit
schemas are noted as a possible future item but are not adopted here, as they cut
against the filesystem-first control plane (ADR-0001).

## Consequences

- Two new leaf policies with no dependents; zero change to existing behavior.
- Least-privilege write scope becomes expressible per role, closing the gap
  between "who acts" and "what they may touch."
- Approval decisions gain a shared vocabulary that maps cleanly onto the existing
  `AuthorizationPolicy` and risk gate.
- Attribution: the harvested patterns are credited to the referenced BAO Reel and
  Gstack project; no kit files are vendored.
