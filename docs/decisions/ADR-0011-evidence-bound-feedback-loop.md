# ADR 0011: Evidence-bound development feedback

Date: 2026-10-24. Owner: Sage Smith. Status: accepted for implementation under
the owner's instruction to apply Reliable Reasoning Architecture before building.

## Determination contract

Question: How should ICM turn the proposed requirements/test/repair loop into
enforced behavior without equating passing tests with complete correctness?
Scope: build/quick handoffs, trusted project verification profiles, bounded local
execution, repair evidence, candidate identity, closure and promotion. Preserve
discovery/decision/review behavior and explicitly simulated dry runs.
Stop when reproducible acceptance exercises reject empty success, failed checks,
stale verification and stale approvals, and existing relevant checks pass.

## Inputs and claims

| ID | Proposition | Epistemic state | Verification | Method/source |
| --- | --- | --- | --- | --- |
| F1 | The owner authorized implementation after reasoning review. | fact | verified | Conversation instruction, 2026-10-24 |
| D1 | Empty Markdown and `{}` artifacts could close a build. | deterministic_result | verified | Controlled injected agent at baseline 40bfce4; evaluation/gates.py and application/service.py |
| D2 | Earlier artifacts were not mandatory inputs in later prompts. | deterministic_result | verified | Controlled invocation capture; agents/prompting.py and application/service.py |
| D3 | A candidate changed after testing and approval could be promoted. | deterministic_result | verified | Temporary Git worktree reproduction; modes/catalog.py and workspace/git.py |
| D4 | Baseline checks passed: 172 tests, one opt-in live test skipped. | deterministic_result | verified | pytest, layout/architecture validators and ruff at 40bfce4 |
| I1 | A trusted project profile plus harness-owned execution is stronger than model-written test claims. | supported_inference | verified | D1; alternative: independent external CI; defeat if the profile or runner is writable by an adversarial agent |
| J1 | Implement enforcement before more routing sophistication. | interpretive_conclusion | not_applicable | Owner-authorized engineering judgment; prioritize measurable acceptance gaps |
| U1 | Project-specific acceptance completeness is unknown. | unresolved_question | unverified | Requires a reviewed profile for each real project; do not invent requirements or claim perfection |
| U2 | OS/container security against a malicious same-user process is not established. | unresolved_question | unverified | Local profiles and fingerprints are integrity checks, not a security sandbox |

All claims apply to the inspected baseline as of the date above. D1-D4 were
produced by tools; I1 and J1 are model analysis. F1 is a human instruction.
Provenance edges: F1 authorizes J1; D1 supports I1; D1-D3 support the changes below;
U1 and U2 limit every resulting correctness/security claim.

## Decision and alternatives

1. Capture a schema-validated project profile at round creation, outside the
   mutable product worktree. Bind named requirements to named executable checks.
   Missing configuration blocks actual build acceptance, rather than silently
   falling back to self-attestation. Existing non-build work stays usable.
2. Deliver immutable prior-artifact references and required contents explicitly.
   Return failure diagnostics to the writer/planner; do not rely on wiki ranking.
3. Have the harness run commands and capture status, output and duration. Keep
   model judgment separate. An exit-code check establishes only that its command
   succeeded; optional test-result parsing supplies counts/skips.
4. Make close nonmutating. Require matching candidate contents at acceptance,
   approval and promotion; reject destination changes pending renewed verification.
5. Keep environment setup/reset/readiness/teardown and frontend checks in reusable
   profiles. Do not require Figma, Storybook, network access or credentials globally.
6. Attribute code-model success only after executable verification, not merely a
   writer's report. Preserve bounded attempts and persistent failure evidence.

Rejected: a larger model or advisory semantic grader as the authoritative gate;
unreviewed model-selected shell commands; blanket read-only test execution;
automatically claiming skipped/live integrations have passed.

## Verification and unresolved work

Exercise false success, failed/empty test results, timeout/cancellation, profile
tampering, source mutation by a check, artifact handoff and repair, post-test and
post-approval edits, destination movement, and successful exact-candidate promotion.
Use real local processes and temporary Git repositories; no external model required.
Retain current live-agent smoke as explicitly opt-in and report whether it ran.

Minimum next action: implement these mechanisms and retain the resulting check
evidence in this repository. For a real deployment, the project owner must supply
and review meaningful checks. No current result establishes full application
correctness, production readiness, or hostile-process containment.
