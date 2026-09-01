from typing import Protocol

from icm_harness.kernel.contracts import ModelCandidate


class CorrelationProvider(Protocol):
    def correlation(self, left: str, right: str) -> float: ...


class HeuristicCorrelation:
    def __init__(self, candidates: list[ModelCandidate]):
        self.by_name = {x.name: x for x in candidates}

    def correlation(self, left: str, right: str) -> float:
        if left == right:
            return 1.0
        a, b = self.by_name.get(left), self.by_name.get(right)
        if not a or not b:
            return 0.25
        if a.family == b.family:
            return 0.75
        if a.provider == b.provider:
            return 0.50
        return 0.20
