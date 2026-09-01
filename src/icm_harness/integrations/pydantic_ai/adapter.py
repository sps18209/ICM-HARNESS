"""In-process agent adapter (pydantic-ai).

Provides a ``StageAgent`` (:mod:`icm_harness.agents.contracts`) that drives a
pydantic-ai ``Agent`` with a typed output schema, as an alternative to the
Codex CLI agent. Injected at the application layer:
``HarnessApplication(root, agent=PydanticAIStageAgent(model=...))``.

Raises :class:`IntegrationUnavailable` when pydantic-ai is not installed.
"""

from __future__ import annotations

from icm_harness.agents.contracts import StageInvocation
from icm_harness.agents.errors import StageAgentError, StageCancelled
from icm_harness.agents.prompting import render_stage_prompt
from icm_harness.kernel.contracts import StageResult, StageStatus
from icm_harness.kernel.errors import IntegrationUnavailable

_VALID_STATUS = {s.value for s in StageStatus}


def make_agent(*, model: str, instructions: str, output_type=None, capabilities=None):
    try:
        from pydantic_ai import Agent
    except ImportError as exc:
        raise IntegrationUnavailable(
            "Install extras: pip install 'icm-production-harness[ai]'"
        ) from exc
    kwargs = {"instructions": instructions}
    if output_type is not None:
        kwargs["output_type"] = output_type
    if capabilities is not None:
        kwargs["capabilities"] = capabilities
    return Agent(model, **kwargs)


def _stage_output_type():
    """Build the structured output model (needs pydantic at call time)."""
    try:
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise IntegrationUnavailable(
            "Install extras: pip install 'icm-production-harness[ai]'"
        ) from exc

    class StageOutput(BaseModel):
        status: str = Field(description="one of: pass, fail, blocked, retryable, cancelled")
        summary: str
        artifacts: dict[str, str] = Field(default_factory=dict)
        return_to: str | None = None
        trigger_codes: list[str] = Field(default_factory=list)

    return StageOutput


class PydanticAIStageAgent:
    def __init__(self, *, model: str, instructions: str | None = None):
        self.model = model
        self.instructions = instructions or (
            "Execute exactly one stage of the ICM harness and return structured output."
        )
        self._agent = None

    def _ensure_agent(self):
        if self._agent is None:
            self._agent = make_agent(
                model=self.model,
                instructions=self.instructions,
                output_type=_stage_output_type(),
            )
        return self._agent

    async def run(self, invocation: StageInvocation) -> StageResult:
        if invocation.cancel_requested():
            raise StageCancelled(f"round {invocation.round_id} was cancelled")
        agent = self._ensure_agent()
        result = await agent.run(render_stage_prompt(invocation))
        if invocation.cancel_requested():
            raise StageCancelled(f"round {invocation.round_id} was cancelled")
        output = result.output
        status_value = str(getattr(output, "status", "")).lower()
        if status_value not in _VALID_STATUS:
            raise StageAgentError(f"agent returned invalid status: {status_value!r}")
        return StageResult(
            StageStatus(status_value),
            str(getattr(output, "summary", "")),
            artifacts={str(k): str(v) for k, v in (getattr(output, "artifacts", {}) or {}).items()},
            return_to=getattr(output, "return_to", None),
            trigger_codes=tuple(str(c) for c in getattr(output, "trigger_codes", ()) or ()),
            metadata={"provider": "pydantic-ai", "model": self.model},
        )
