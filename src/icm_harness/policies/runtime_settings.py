from dataclasses import dataclass, replace

from icm_harness.context.triggers import ContextTrigger


@dataclass(frozen=True, slots=True)
class AgentRunSettings:
    context_tier: int
    max_output_tokens: int
    reasoning_effort: str
    allow_write_tools: bool
    allow_network_tools: bool
    max_tool_calls: int
    max_subagents: int


class SituationalSettingsPolicy:
    """Cheap-by-default stage settings with explicit trigger-based escalation."""

    BASE = {
        "quick.execute": AgentRunSettings(1, 1800, "low", True, False, 8, 0),
        "quick.verify": AgentRunSettings(1, 1500, "low", False, False, 6, 0),
        "discovery.frame": AgentRunSettings(1, 2200, "medium", False, False, 8, 0),
        "discovery.explore": AgentRunSettings(1, 3000, "medium", False, False, 12, 2),
        "discovery.research": AgentRunSettings(2, 4500, "medium", False, True, 30, 4),
        "discovery.adversarial": AgentRunSettings(2, 4000, "high", False, False, 15, 3),
        "discovery.synthesis": AgentRunSettings(2, 3500, "high", False, False, 8, 0),
        "discovery.validate": AgentRunSettings(2, 3000, "high", False, True, 15, 2),
        "build.planner": AgentRunSettings(2, 4200, "high", False, False, 18, 2),
        "build.writer": AgentRunSettings(2, 4200, "medium", True, False, 24, 0),
        "build.tester": AgentRunSettings(2, 4000, "high", False, False, 24, 2),
        "build.close": AgentRunSettings(1, 1800, "low", True, False, 8, 0),
        "decision.frame": AgentRunSettings(1, 2200, "medium", False, False, 8, 0),
        "decision.evidence": AgentRunSettings(2, 4000, "medium", False, True, 24, 3),
        "decision.options": AgentRunSettings(1, 3000, "medium", False, False, 10, 2),
        "decision.adversarial": AgentRunSettings(2, 4200, "high", False, False, 16, 4),
        "decision.decide": AgentRunSettings(2, 3200, "high", False, False, 8, 0),
        "decision.validate": AgentRunSettings(2, 3000, "high", False, True, 12, 2),
        "review.ingest": AgentRunSettings(1, 1800, "low", False, False, 8, 0),
        "review.reconstruct": AgentRunSettings(1, 2600, "medium", False, False, 10, 0),
        "review.inspect": AgentRunSettings(2, 3600, "high", False, False, 20, 2),
        "review.adversarial": AgentRunSettings(2, 3600, "high", False, False, 15, 3),
        "review.findings": AgentRunSettings(1, 2800, "medium", False, False, 8, 0),
    }

    def settings(
        self,
        stage_ref: str,
        *,
        stakes: float,
        triggers: tuple[ContextTrigger, ...] = (),
    ) -> AgentRunSettings:
        base = self.BASE.get(stage_ref, AgentRunSettings(1, 2500, "medium", False, False, 10, 0))
        result = base

        # Stakes change rigor but do not automatically load the world.
        if stakes >= 0.8:
            result = replace(
                result,
                reasoning_effort="high",
                max_output_tokens=min(6000, result.max_output_tokens + 800),
            )

        # Only situational signals are allowed to widen context/tool budgets.
        trigger_set = set(triggers)
        if ContextTrigger.CONTEXT_GAP in trigger_set:
            result = replace(result, context_tier=max(result.context_tier, 2))
        if ContextTrigger.ARCHITECTURE_UNKNOWN in trigger_set:
            result = replace(
                result,
                context_tier=max(result.context_tier, 3),
                max_subagents=max(result.max_subagents, 2),
            )
        if ContextTrigger.CROSS_FILE_COUPLING in trigger_set:
            result = replace(
                result,
                context_tier=max(result.context_tier, 3),
                max_tool_calls=min(40, result.max_tool_calls + 8),
            )
        if ContextTrigger.TEST_FAILURE_PLAN in trigger_set:
            result = replace(
                result, context_tier=max(result.context_tier, 3), reasoning_effort="high"
            )
        if ContextTrigger.CONTRADICTORY_EVIDENCE in trigger_set:
            result = replace(
                result,
                context_tier=max(result.context_tier, 3),
                max_subagents=max(result.max_subagents, 3),
                reasoning_effort="high",
            )
        if ContextTrigger.TOOL_OUTPUT_TOO_LARGE in trigger_set:
            # Do not respond to token pressure by increasing the output budget.
            result = replace(result, max_tool_calls=max(4, result.max_tool_calls - 4))
        return result
