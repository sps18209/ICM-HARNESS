from collections.abc import Iterable
from dataclasses import dataclass, field

from icm_harness.context.budgets import ContextBudget
from icm_harness.context.ranking import ContextRanker
from icm_harness.context.retrieval import ContextProvider
from icm_harness.context.triggers import ContextTrigger
from icm_harness.kernel.contracts import ContextBundle, ContextItem

TRIGGER_TIER_FLOOR = {
    ContextTrigger.CONTEXT_GAP: 2,
    ContextTrigger.ARCHITECTURE_UNKNOWN: 3,
    ContextTrigger.CROSS_FILE_COUPLING: 3,
    ContextTrigger.TEST_FAILURE_PLAN: 3,
    ContextTrigger.HIGH_STAKES: 2,
    ContextTrigger.CONTRADICTORY_EVIDENCE: 3,
    ContextTrigger.TOOL_OUTPUT_TOO_LARGE: 1,
}


@dataclass
class ContextEngine:
    providers: list[ContextProvider]
    ranker: ContextRanker = field(default_factory=ContextRanker)

    def resolve(
        self,
        *,
        query: str,
        stage_ref: str,
        budget: ContextBudget,
        base_items: Iterable[ContextItem] = (),
        triggers: Iterable[ContextTrigger] = (),
        requested_tier: int = 0,
    ) -> ContextBundle:
        trigger_tuple = tuple(triggers)
        tier = requested_tier
        for trigger in trigger_tuple:
            tier = max(tier, TRIGGER_TIER_FLOOR[trigger])
        tier = min(tier, budget.max_tier)

        all_items = list(base_items)
        for provider in self.providers:
            all_items.extend(provider.retrieve(query, tier, stage_ref))

        selected = self.ranker.select(all_items, budget.tokens, tier)
        return ContextBundle(
            selected,
            sum(x.tokens for x in selected),
            budget.tokens,
            tier,
            tuple(x.value for x in trigger_tuple),
        )
