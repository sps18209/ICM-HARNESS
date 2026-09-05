from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    state_db: str = ".harness/runtime/state.sqlite3"
    audit_log: str = ".harness/runtime/audit.jsonl"
    lease_ttl_seconds: int = 90
    heartbeat_seconds: int = 20
    stage_timeout_seconds: int = 1800
    global_concurrency: int = 8
    max_attempts: int = 3
    max_stage_transitions: int = 100


@dataclass(frozen=True, slots=True)
class ContextConfig:
    base_budget_tokens: int = 1800
    max_budget_tokens: int = 24000
    max_tier: int = 4


@dataclass(frozen=True, slots=True)
class AgentConfig:
    provider: str = "claude-cli"
    executable: str = "claude"
    model: str = "default"
    extra_args: tuple[str, ...] = ()
    inherit_environment: tuple[str, ...] = (
        "PATH",
        "LANG",
        "LC_ALL",
        "TERM",
        "TMPDIR",
        "USER",
        "HOME",
    )


@dataclass(frozen=True, slots=True)
class WorkspaceConfig:
    strategy: str = "worktree"
    worktree_root: str = ".harness/worktrees"


@dataclass(frozen=True, slots=True)
class WebConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    poll_interval_ms: int = 1500


@dataclass(frozen=True, slots=True)
class ModelConfig:
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
class HarnessConfig:
    runtime: RuntimeConfig = RuntimeConfig()
    context: ContextConfig = ContextConfig()
    agent: AgentConfig = AgentConfig()
    workspace: WorkspaceConfig = WorkspaceConfig()
    web: WebConfig = WebConfig()
    models: tuple[ModelConfig, ...] = field(default_factory=tuple)
    stage_budgets: Mapping[str, int] = field(default_factory=dict)


def _table(data: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, Mapping):
        raise ValueError(f"configuration section [{name}] must be a table")
    return value


def _known(cls, data: Mapping[str, Any]) -> dict[str, Any]:
    allowed = cls.__dataclass_fields__.keys()
    unknown = set(data) - set(allowed)
    if unknown:
        raise ValueError(f"unknown {cls.__name__} settings: {', '.join(sorted(unknown))}")
    return dict(data)


def default_config_text() -> str:
    return resources.files("icm_harness").joinpath("defaults.toml").read_text(encoding="utf-8")


def write_default_config(path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text(default_config_text(), encoding="utf-8")
    return target


def load_config(root: str | Path, *, environ: Mapping[str, str] | None = None) -> HarnessConfig:
    root_path = Path(root).resolve()
    config_path = root_path / ".harness/config.toml"
    raw = (
        default_config_text()
        if not config_path.exists()
        else config_path.read_text(encoding="utf-8")
    )
    data = tomllib.loads(raw)
    env = os.environ if environ is None else environ

    runtime = RuntimeConfig(**_known(RuntimeConfig, _table(data, "runtime")))
    context = ContextConfig(**_known(ContextConfig, _table(data, "context")))

    agent_data = _known(AgentConfig, _table(data, "agent"))
    if "extra_args" in agent_data:
        agent_data["extra_args"] = tuple(agent_data["extra_args"])
    if "inherit_environment" in agent_data:
        agent_data["inherit_environment"] = tuple(agent_data["inherit_environment"])
    if env.get("ICM_AGENT_PROVIDER"):
        agent_data["provider"] = env["ICM_AGENT_PROVIDER"]
    if env.get("ICM_AGENT_EXECUTABLE"):
        agent_data["executable"] = env["ICM_AGENT_EXECUTABLE"]
    if env.get("ICM_AGENT_MODEL"):
        agent_data["model"] = env["ICM_AGENT_MODEL"]
    agent = AgentConfig(**agent_data)

    workspace = WorkspaceConfig(**_known(WorkspaceConfig, _table(data, "workspace")))
    if workspace.strategy not in {"worktree", "in_place"}:
        raise ValueError("workspace.strategy must be 'worktree' or 'in_place'")
    web = WebConfig(**_known(WebConfig, _table(data, "web")))

    model_configs = []
    for name, values in _table(data, "models").items():
        if not isinstance(values, Mapping):
            raise ValueError(f"models.{name} must be a table")
        payload = dict(values)
        payload.setdefault("name", name)
        payload["capabilities"] = frozenset(payload.get("capabilities", ()))
        model_configs.append(ModelConfig(**_known(ModelConfig, payload)))

    budget_values = _table(data, "stage_budgets")
    stage_budgets = {str(key): int(value) for key, value in budget_values.items()}
    return HarnessConfig(
        runtime, context, agent, workspace, web, tuple(model_configs), stage_budgets
    )
