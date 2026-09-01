from dataclasses import dataclass

from icm_harness.kernel.contracts import ModelCandidate, ModelRequest, RoutingDecision
from icm_harness.kernel.errors import NoEligibleModel
from icm_harness.routing.correlation import CorrelationProvider
from icm_harness.routing.learning import BayesianPerformanceStore


@dataclass(frozen=True, slots=True)
class RoutingWeights:
    quality: float = 1.0
    reliability: float = 0.8
    cost: float = 0.25
    latency: float = 0.15
    risk: float = 0.7
    exploration: float = 0.08
    correlation: float = 0.35


class ModelRouter:
    def __init__(self, candidates, performance, correlation, weights=None):
        self.candidates: list[ModelCandidate] = candidates
        self.performance: BayesianPerformanceStore = performance
        self.correlation: CorrelationProvider = correlation
        self.weights = weights or RoutingWeights()

    def choose(self, request: ModelRequest) -> RoutingDecision:
        eligible = [m for m in self.candidates if self._eligible(m, request)]
        if not eligible:
            raise NoEligibleModel(f"no eligible model for {request.stage_ref}")
        return max((self._score(m, request) for m in eligible), key=lambda x: x.utility)

    def _eligible(self, model: ModelCandidate, request: ModelRequest) -> bool:
        if request.input_tokens + request.expected_output_tokens > model.max_context:
            return False
        if not request.required_capabilities.issubset(model.capabilities):
            return False
        if model.privacy_class > request.max_privacy_class:
            return False
        if model.latency_ms > request.max_latency_ms:
            return False
        return not (
            request.max_cost_usd is not None and self._cost(model, request) > request.max_cost_usd
        )

    def _cost(self, model: ModelCandidate, request: ModelRequest) -> float:
        return (
            request.input_tokens / 1_000_000 * model.input_cost_per_million
            + request.expected_output_tokens / 1_000_000 * model.output_cost_per_million
        )

    def _score(self, model: ModelCandidate, request: ModelRequest) -> RoutingDecision:
        posterior = self.performance.posterior(
            model.name, request.stage_ref, request.task_class, model.quality_prior
        )
        cost = self._cost(model, request)
        latency_norm = model.latency_ms / max(1, request.max_latency_ms)
        risk_penalty = request.stakes * (1.0 - model.reliability)
        corr = (
            self.correlation.correlation(request.writer_model, model.name)
            if request.writer_model
            else 0.0
        )
        w = self.weights
        utility = (
            w.quality * posterior.mean
            + w.reliability * model.reliability
            + w.exploration * posterior.exploration_bonus
            - w.cost * cost
            - w.latency * latency_norm
            - w.risk * risk_penalty
            - w.correlation * corr
        )
        return RoutingDecision(
            model,
            utility,
            cost,
            posterior.mean,
            {
                "posterior_quality": posterior.mean,
                "reliability": model.reliability,
                "cost_usd": cost,
                "latency_normalized": latency_norm,
                "risk_penalty": risk_penalty,
                "correlation_penalty": corr,
                "exploration_bonus": posterior.exploration_bonus,
            },
        )
