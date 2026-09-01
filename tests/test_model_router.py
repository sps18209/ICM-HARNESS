from dataclasses import replace

from icm_harness.kernel.contracts import ModelCandidate, ModelRequest
from icm_harness.routing.correlation import HeuristicCorrelation
from icm_harness.routing.learning import BayesianPerformanceStore
from icm_harness.routing.model_router import ModelRouter


def candidate(name, provider, family, quality, cost):
    return ModelCandidate(
        name=name,
        provider=provider,
        family=family,
        max_context=100_000,
        input_cost_per_million=cost,
        output_cost_per_million=cost,
        latency_ms=1000,
        reliability=0.99,
        quality_prior=quality,
        capabilities=frozenset({"text", "code"}),
    )


def request(writer=None):
    return ModelRequest(
        stage_ref="build.tester" if writer else "build.writer",
        task_class="code",
        input_tokens=1000,
        expected_output_tokens=1000,
        stakes=0.9,
        max_latency_ms=5000,
        max_cost_usd=1.0,
        required_capabilities=frozenset({"code"}),
        writer_model=writer,
    )


def test_hard_capability_constraints(tmp_path):
    a = candidate("a", "p1", "f1", 0.9, 5)
    b = replace(candidate("b", "p2", "f2", 0.8, 1), capabilities=frozenset({"text"}))
    models = [a, b]
    router = ModelRouter(
        models, BayesianPerformanceStore(tmp_path / "p.db"), HeuristicCorrelation(models)
    )
    assert router.choose(request()).model.name == "a"


def test_tester_penalizes_writer_correlated_model(tmp_path):
    a = candidate("a", "p1", "f1", 0.88, 1)
    b = candidate("b", "p2", "f2", 0.87, 1)
    models = [a, b]
    router = ModelRouter(
        models, BayesianPerformanceStore(tmp_path / "p.db"), HeuristicCorrelation(models)
    )
    assert router.choose(request("a")).model.name == "b"
