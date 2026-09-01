from __future__ import annotations

import json

import anyio
import pytest

from icm_harness.context.budgets import ContextBudget
from icm_harness.context.engine import ContextEngine
from icm_harness.integrations.aider_repo_map.adapter import (
    RepoMapContextProvider,
    RepoMapPolicy,
)
from icm_harness.integrations.llmlingua.adapter import LLMLinguaCompressor, LLMLinguaPolicy
from icm_harness.integrations.portkey.adapter import PortkeyGateway
from icm_harness.integrations.promptfoo.adapter import run_eval, summarize_output
from icm_harness.kernel.errors import IntegrationUnavailable

# --- aider_repo_map: a real, dependency-free ContextProvider ----------------


def _make_repo(root):
    (root / "pkg").mkdir()
    (root / "pkg" / "payments.py").write_text(
        "import os\n\nclass PaymentGateway:\n    def charge(self):\n        return 1\n",
        encoding="utf-8",
    )
    (root / "pkg" / "unrelated.py").write_text("def helper():\n    return 0\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_payments.py").write_text(
        "def test_charge():\n    assert True\n", encoding="utf-8"
    )
    (root / "node_modules").mkdir()
    (root / "node_modules" / "junk.js").write_text("noop\n", encoding="utf-8")


def test_repo_map_gated_below_activation_tier(tmp_path):
    _make_repo(tmp_path)
    provider = RepoMapContextProvider(tmp_path)
    assert provider.retrieve("payment gateway", tier=1, stage_ref="build.planner") == ()


def test_repo_map_boosts_mentioned_and_changed_files(tmp_path):
    _make_repo(tmp_path)
    provider = RepoMapContextProvider(
        tmp_path, changed_files=frozenset({"pkg/payments.py"})
    )
    items = provider.retrieve("payment gateway", tier=2, stage_ref="build.planner")
    keys = [item.key for item in items]

    assert "pkg/payments.py" in keys
    assert "node_modules/junk.js" not in keys  # ignored dir
    # payments.py is both mentioned and changed → ranked above unrelated.py
    assert keys.index("pkg/payments.py") == 0
    top = items[0]
    assert "PaymentGateway" in top.content  # python symbol map
    assert top.graph_relevance > 0
    # the test neighbor is surfaced because its target changed
    assert "tests/test_payments.py" in keys


def test_repo_map_respects_token_budget(tmp_path):
    _make_repo(tmp_path)
    provider = RepoMapContextProvider(
        tmp_path,
        policy=RepoMapPolicy(max_tokens=1),
        changed_files=frozenset({"pkg/payments.py"}),
    )
    items = provider.retrieve("payment", tier=2, stage_ref="build.planner")
    assert sum(item.tokens for item in items) <= 1


def test_repo_map_integrates_with_context_engine(tmp_path):
    _make_repo(tmp_path)
    engine = ContextEngine([RepoMapContextProvider(tmp_path)])
    bundle = engine.resolve(
        query="payment gateway",
        stage_ref="build.planner",
        budget=ContextBudget(tokens=5000, max_tier=3),
        requested_tier=2,
    )
    assert any("payments.py" in item.key for item in bundle.items)


# --- llmlingua: pure policy + guarded compression ---------------------------


def test_llmlingua_policy_thresholds():
    disabled = LLMLinguaPolicy(enabled=False)
    assert disabled.should_compress("x" * 100_000) is False
    enabled = LLMLinguaPolicy(enabled=True, minimum_source_tokens=10)
    assert enabled.should_compress("short") is False
    assert enabled.should_compress("word " * 200) is True


def test_llmlingua_passthrough_when_policy_declines():
    comp = LLMLinguaCompressor(LLMLinguaPolicy(enabled=False))
    assert comp.compress("keep me", 10) == "keep me"


def test_llmlingua_requires_sdk_when_compression_is_needed():
    comp = LLMLinguaCompressor(LLMLinguaPolicy(enabled=True, minimum_source_tokens=1))
    with pytest.raises(IntegrationUnavailable):
        comp.compress("word " * 50, target_tokens=10)


# --- portkey: pure request building -----------------------------------------


def test_portkey_builds_minimal_and_full_requests():
    gw = PortkeyGateway()
    minimal = gw.build_request(model="m", messages=[{"role": "user", "content": "hi"}])
    assert minimal == {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
    full = gw.build_request(
        model="m", messages=[], max_tokens=64, temperature=0.2
    )
    assert full["max_tokens"] == 64 and full["temperature"] == 0.2


# --- promptfoo: pure result reduction + guarded exec ------------------------


def test_promptfoo_summarize_pass_and_fail(tmp_path):
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps({"results": {"stats": {"successes": 3, "failures": 0}}}))
    report = summarize_output(str(ok), returncode=0)
    assert report.passed and report.total == 3 and report.failures == 0

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"results": {"stats": {"successes": 1, "failures": 2}}}))
    assert summarize_output(str(bad), returncode=0).passed is False

    assert summarize_output(str(tmp_path / "missing.json")).passed is False


def test_promptfoo_run_eval_requires_binary():
    with pytest.raises(IntegrationUnavailable):
        run_eval("nonexistent.yaml")


# --- guarded SDK adapters ---------------------------------------------------


def test_hatchet_requires_sdk():
    from icm_harness.integrations.hatchet.adapter import HatchetDurableExecutor, require_hatchet

    with pytest.raises(IntegrationUnavailable):
        require_hatchet()
    with pytest.raises(IntegrationUnavailable):
        anyio.run(HatchetDurableExecutor().submit, "wf", {})


def test_e2b_requires_sdk():
    from icm_harness.integrations.e2b.adapter import E2BSandboxRunner

    with pytest.raises(IntegrationUnavailable):
        E2BSandboxRunner().run("echo hi")


def test_river_requires_sdk():
    from icm_harness.integrations.river.adapter import make_thompson_policy

    with pytest.raises(IntegrationUnavailable):
        make_thompson_policy()


def test_mcp_requires_sdk():
    from icm_harness.integrations.mcp.adapter import (
        MCPServerConfig,
        MCPToolProvider,
        require_mcp_sdk,
    )

    with pytest.raises(IntegrationUnavailable):
        require_mcp_sdk()
    provider = MCPToolProvider(MCPServerConfig(command=("serve",)))
    with pytest.raises(IntegrationUnavailable):
        anyio.run(provider.list_tools)


def test_openlit_init_guarded_but_metrics_work_offline():
    from icm_harness.integrations.openlit.adapter import OpenLITMetrics, initialize_openlit

    with pytest.raises(IntegrationUnavailable):
        initialize_openlit()
    metrics = OpenLITMetrics()
    metrics.increment("rounds", 2)
    metrics.increment("rounds")
    assert metrics.get("rounds") == 3.0
    assert metrics.get("missing") == 0.0


def test_serena_gated_and_guarded(tmp_path):
    from icm_harness.integrations.serena.adapter import SerenaContextProvider

    provider = SerenaContextProvider()
    assert provider.retrieve("q", tier=0, stage_ref="build.planner") == ()
    with pytest.raises(IntegrationUnavailable):
        provider.retrieve("q", tier=2, stage_ref="build.planner")


def test_pydantic_ai_requires_extras():
    from icm_harness.integrations.pydantic_ai.adapter import PydanticAIStageAgent, make_agent

    with pytest.raises(IntegrationUnavailable):
        make_agent(model="test", instructions="x")
    # Building the underlying agent (which the StageAgent does lazily on run)
    # surfaces the same clear error when the extra is not installed.
    agent = PydanticAIStageAgent(model="test")
    with pytest.raises(IntegrationUnavailable):
        agent._ensure_agent()
