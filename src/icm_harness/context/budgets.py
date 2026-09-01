from dataclasses import dataclass


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


@dataclass(frozen=True, slots=True)
class ContextBudget:
    tokens: int
    max_tier: int

    def __post_init__(self) -> None:
        if self.tokens <= 0:
            raise ValueError("tokens must be positive")
        if not 0 <= self.max_tier <= 4:
            raise ValueError("max_tier must be between 0 and 4")
