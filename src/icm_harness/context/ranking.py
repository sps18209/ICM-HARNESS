from collections.abc import Iterable
from dataclasses import dataclass

from icm_harness.kernel.contracts import ContextItem
from icm_harness.kernel.errors import ContextBudgetExceeded


@dataclass(frozen=True, slots=True)
class RankingWeights:
    graph: float = 0.20
    query: float = 0.30
    stage: float = 0.20
    diff: float = 0.10
    test: float = 0.10
    authority: float = 0.10


class ContextRanker:
    def __init__(self, weights: RankingWeights | None = None):
        self.weights = weights or RankingWeights()

    def score(self, item: ContextItem) -> float:
        w = self.weights
        return (
            w.graph * item.graph_relevance
            + w.query * item.query_relevance
            + w.stage * item.stage_relevance
            + w.diff * item.diff_relevance
            + w.test * item.test_relevance
            + w.authority * item.authority
        )

    def select(
        self, items: Iterable[ContextItem], budget_tokens: int, max_tier: int
    ) -> tuple[ContextItem, ...]:
        eligible = [x for x in items if x.tier <= max_tier]
        required = [x for x in eligible if x.required]
        required_tokens = sum(x.tokens for x in required)
        if required_tokens > budget_tokens:
            raise ContextBudgetExceeded(
                f"required context uses {required_tokens} tokens, budget={budget_tokens}"
            )
        chosen = list(required)
        remaining = budget_tokens - required_tokens
        optional = [x for x in eligible if not x.required]
        optional.sort(
            key=lambda x: (self.score(x) / max(x.tokens, 1), self.score(x)),
            reverse=True,
        )
        for item in optional:
            if item.tokens <= remaining:
                chosen.append(item)
                remaining -= item.tokens
        return tuple(chosen)
