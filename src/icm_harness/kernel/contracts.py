from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Mode(StrEnum):
    DISCOVERY = "discovery"
    BUILD = "build"
    DECISION = "decision"
    REVIEW = "review"
    QUICK = "quick"


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocked"
    RETRYABLE = "retryable"
    CANCELLED = "cancelled"


class TaskIntent(StrEnum):
    AUTO = "auto"
    BUILD = "build"
    INVESTIGATE = "investigate"
    DECIDE = "decide"
    REVIEW = "review"
    QUICK = "quick"


@dataclass(frozen=True, slots=True)
class TaskProfile:
    objective: str
    intent: TaskIntent = TaskIntent.AUTO
    specification_clarity: float = 0.5
    epistemic_uncertainty: float = 0.5
    stakes: float = 0.5
    reversibility: float = 0.5
    production_change_required: bool = False
    code_intensity: float = 0.0
    research_intensity: float = 0.0
    tool_intensity: float = 0.0
    privacy_restricted: bool = False
    latency_tolerance_ms: int = 10_000
    budget_usd: float | None = None
    required_capabilities: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        for name in (
            "specification_clarity",
            "epistemic_uncertainty",
            "stakes",
            "reversibility",
            "code_intensity",
            "research_intensity",
            "tool_intensity",
        ):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class StageSpec:
    mode: Mode
    name: str
    mutates_workspace: bool = False
    requires_human_gate: bool = False
    default_context_tier: int = 0
    required_outputs: tuple[str, ...] = ()
    permitted_return_stages: tuple[str, ...] = ()

    @property
    def ref(self) -> str:
        return f"{self.mode.value}.{self.name}"


@dataclass(frozen=True, slots=True)
class ModeSpec:
    mode: Mode
    stages: tuple[StageSpec, ...]


@dataclass(frozen=True, slots=True)
class ModeRoute:
    modes: tuple[Mode, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class StageResult:
    status: StageStatus
    summary: str
    artifacts: Mapping[str, str] = field(default_factory=dict)
    return_to: str | None = None
    trigger_codes: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelCandidate:
    name: str
    provider: str
    family: str
    max_context: int
    input_cost_per_million: float
    output_cost_per_million: float
    latency_ms: int
    reliability: float
    quality_prior: float
    capabilities: frozenset[str] = frozenset()
    privacy_class: int = 0


@dataclass(frozen=True, slots=True)
class ModelRequest:
    stage_ref: str
    task_class: str
    input_tokens: int
    expected_output_tokens: int
    stakes: float
    max_latency_ms: int
    max_cost_usd: float | None
    required_capabilities: frozenset[str]
    max_privacy_class: int = 0
    writer_model: str | None = None


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    model: ModelCandidate
    utility: float
    estimated_cost_usd: float
    posterior_quality: float
    explanation: Mapping[str, float | str]


@dataclass(frozen=True, slots=True)
class ContextItem:
    key: str
    content: str
    source: str
    tokens: int
    query_relevance: float = 0.0
    graph_relevance: float = 0.0
    stage_relevance: float = 0.0
    diff_relevance: float = 0.0
    test_relevance: float = 0.0
    authority: float = 0.0
    required: bool = False
    tier: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ContextBundle:
    items: Sequence[ContextItem]
    used_tokens: int
    budget_tokens: int
    tier: int
    triggers: tuple[str, ...] = ()
