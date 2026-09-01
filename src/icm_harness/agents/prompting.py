from __future__ import annotations

from icm_harness.agents.contracts import StageInvocation
from icm_harness.agents.prompts import PLANNER_INVARIANTS, TESTER_INVARIANTS, WRITER_INVARIANTS


def _role_invariants(stage_ref: str) -> str:
    if stage_ref == "build.planner":
        return PLANNER_INVARIANTS
    if stage_ref == "build.writer":
        return WRITER_INVARIANTS
    if stage_ref == "build.tester":
        return TESTER_INVARIANTS
    return "Follow the active stage contract and do not perform work assigned to later stages."


def render_stage_prompt(invocation: StageInvocation) -> str:
    stage = invocation.stage
    required_outputs = ", ".join(stage.required_outputs) or "none"
    permitted_returns = ", ".join(stage.permitted_return_stages) or "none"
    context_text = (
        "\n\n".join(
            f"--- {item.key} ({item.source}) ---\n{item.content}"
            for item in invocation.context.items
        )
        or "No additional context was selected."
    )
    mutation_rule = (
        "You may modify files inside the working directory as required by the objective."
        if stage.mutates_workspace
        else "Do not modify product source, tests, dependencies, or configuration."
    )
    return f"""You are executing one stage of the ICM production harness.

Round: {invocation.round_id}
Stage: {stage.ref}
Objective: {invocation.profile.objective}
Attempt: {invocation.attempt}
Working directory: {invocation.workspace}

Stage rules:
{_role_invariants(stage.ref).strip()}
{mutation_rule}
Required artifact names: {required_outputs}
Permitted return stages: {permitted_returns}

Return a JSON object matching the supplied schema. Put the complete textual content of every
required artifact in the `artifacts` object keyed by its exact required filename. Do not write
round artifacts into the product tree; the harness persists returned artifacts itself. Use
`status=pass` only when this stage's work and required artifacts are complete. Use `retryable`
for a transient failure, `blocked` when human input is required, and `fail` for a substantive
failure. A `return_to` value is allowed only when listed above.

Selected context (tier {invocation.context.tier}, {invocation.context.used_tokens}/
{invocation.context.budget_tokens} estimated tokens):
{context_text}
"""
