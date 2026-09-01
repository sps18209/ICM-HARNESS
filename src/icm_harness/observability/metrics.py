from dataclasses import dataclass, field


@dataclass
class InMemoryMetrics:
    counters: dict[str, float] = field(default_factory=dict)

    def increment(self, name: str, value: float = 1.0) -> None:
        self.counters[name] = self.counters.get(name, 0.0) + value

    def get(self, name: str) -> float:
        return self.counters.get(name, 0.0)
