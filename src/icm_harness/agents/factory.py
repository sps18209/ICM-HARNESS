from __future__ import annotations

from icm_harness.agents.claude_code import ClaudeCodeStageAgent
from icm_harness.agents.codex_cli import CodexCLIStageAgent
from icm_harness.agents.contracts import StageAgent
from icm_harness.agents.dry_run import DryRunStageAgent
from icm_harness.config import AgentConfig


def make_stage_agent(config: AgentConfig, *, dry_run: bool = False) -> StageAgent:
    if dry_run or config.provider == "dry-run":
        return DryRunStageAgent()
    if config.provider == "codex-cli":
        return CodexCLIStageAgent(
            executable=config.executable,
            extra_args=config.extra_args,
            inherit_environment=config.inherit_environment,
        )
    if config.provider == "claude-code":
        # Fall back to the natural binary when the executable is still the shipped
        # default ("codex"), so switching only `provider` to claude-code works.
        executable = config.executable if config.executable != "codex" else "claude"
        return ClaudeCodeStageAgent(
            executable=executable,
            extra_args=config.extra_args,
            inherit_environment=config.inherit_environment,
        )
    raise ValueError(f"unsupported agent provider: {config.provider}")
