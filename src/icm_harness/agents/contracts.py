from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from icm_harness.kernel.contracts import ContextBundle, StageResult, StageSpec, TaskProfile
from icm_harness.policies import AgentRunSettings, AuthorizationPolicy


@dataclass(frozen=True, slots=True)
class StageInvocation:
    round_id: str
    profile: TaskProfile
    stage: StageSpec
    context: ContextBundle
    settings: AgentRunSettings
    workspace: Path
    artifact_dir: Path
    model: str | None
    attempt: int
    authorization: AuthorizationPolicy
    cancel_requested: Callable[[], bool]


class StageAgent(Protocol):
    async def run(self, invocation: StageInvocation) -> StageResult: ...
