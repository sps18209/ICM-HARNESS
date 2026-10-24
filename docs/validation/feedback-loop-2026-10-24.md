# Feedback loop implementation: validation record

This completes the determination initiated in ADR-0011. Decision owner: Sage
Smith. Domain: local software-engineering harness behavior. Applicable date:
2026-10-24. Scope and stopping conditions remain those of ADR-0011.

## Observed results

The new verifier executed this repository's captured project profile directly:

| Check | Observed result |
| --- | --- |
| Python regression/acceptance suite, with fresh JUnit output | 207 passed, 1 skipped; 208 total |
| Architecture validator | Passed |
| Layout validator | Passed |
| Ruff, src/tests/scripts | Passed |
| Python compileall | Passed |
| Extension TypeScript compilation and Node tests | 18 passed, none skipped |
| Extension VSIX packaging | Passed |

The one Python skip is the explicitly opt-in, authenticated live Codex smoke.
It was tightened to require actual CONTRIBUTING.md contents and a passing
harness-owned verification result, but no live provider call is claimed.
Environment: Python 3.12 and Node 24.22.1 locally. CI retains its own Python matrix
and Node 20 job; local results do not establish those remote results in advance.

## Determination claims and trace

| ID | Proposition | Epistemic state | Verification | Operation and dependencies |
| --- | --- | --- | --- | --- |
| V1 | Unsupported success cannot close an actual build against a failing captured check. | deterministic_result | verified | test_false_success_is_rejected_by_real_command; ADR D1; profile.py/runner.py/service.py |
| V2 | A failed check supplies contract, plan and failure output to a subsequent writer, whose repaired product can pass and promote. | deterministic_result | verified | test_repair_gets_original_contract_plan_and_failure_then_promotes_exact_candidate; ADR D2 |
| V3 | Post-test/post-approval candidate edits and destination movement prevent approval/promotion. | deterministic_result | verified | post_verification_edits, destination_movement and close_cannot_edit acceptance exercises; ADR D3 |
| V4 | Missing/stale/empty/all-skipped JUnit reports cannot establish passing test evidence; explicitly allowed mixed skips remain reported. | deterministic_result | verified | junit_counts_and_skips and stale_junit acceptance exercises |
| V5 | Cancellation/timeout stop command descendants and run bounded teardown. | deterministic_result | verified | timeout_kills_descendants, operator_cancellation and total_verification_budget exercises |
| V6 | The controls support greater autonomy within the captured acceptance scope. | supported_inference | verified | V1-V5; alternative is externally hosted CI; limited by profile coverage and process isolation |
| U3 | Live-model reliability over hours and project-specific production correctness remain undetermined. | unresolved_question | unverified | Requires live agent runs, representative real-project profiles and deployment checks |

V1-V5 were produced by reproducible tool execution against temporary Git repos
and actual local subprocesses, using injected deterministic stage agents. V6 is
model synthesis of those observations; its verification field applies to the
identified support, not a universal guarantee. U3 is recorded by the model.

Provenance edges: ADR D1 -> V1; ADR D2 -> V2; ADR D3 -> V3;
test_report_validation -> V4; process_lifecycle_tests -> V5;
V1,V2,V3,V4,V5 -> V6; ADR U1,U2 and U3 limit V6.

Additional adversarial exercises cover protected acceptance-input tampering,
profile replacement after capture, restart handoffs, stale artifacts, in-place
tester mutation, generated-output exclusion, invalid schemas, tracked-output
protection and non-promotable simulation.

## Effect and next actions

The owner's implementation instruction authorized these changes; it did not
declare any downstream application correct. The substantive effect is the new
engine acceptance behavior. Human approval remains scoped to a specific verified
candidate. Project owners must review their profiles and acceptance coverage.
The skill-only fallback is guidance, not the engine's enforced execution path.
OS/container confinement and malicious same-user process resistance remain
outside this implementation's guarantees.

Next actions: review the PR and its CI results, then exercise a real project with
a reviewed acceptance profile. Raw local self-verification output is emitted to
`.harness/runtime/self-verification.json`; the profile and acceptance exercises
in the repository make the checks reproducible without relying on that file.
