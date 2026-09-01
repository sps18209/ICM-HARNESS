from __future__ import annotations

import json

from icm_harness.agents.contracts import StageInvocation
from icm_harness.kernel.contracts import StageResult, StageStatus


class DryRunStageAgent:
    """Deterministic agent for installation checks and end-to-end smoke tests."""

    async def run(self, invocation: StageInvocation) -> StageResult:
        artifacts = {}
        for name in invocation.stage.required_outputs:
            if name.endswith(".json"):
                payload = {
                    "dry_run": True,
                    "round_id": invocation.round_id,
                    "stage": invocation.stage.ref,
                    "objective": invocation.profile.objective,
                    "passed": True,
                }
                if name == "context-manifest.json":
                    payload["context"] = [item.key for item in invocation.context.items]
                artifacts[name] = json.dumps(payload, indent=2, sort_keys=True) + "\n"
            else:
                artifacts[name] = (
                    f"# {invocation.stage.ref}\n\n"
                    f"Dry-run artifact for `{invocation.profile.objective}`.\n\n"
                    "This proves wiring and lifecycle behavior; it is not a "
                    "production agent result.\n"
                )
        return StageResult(
            StageStatus.PASS,
            f"dry-run completed {invocation.stage.ref}",
            artifacts=artifacts,
            metadata={"dry_run": True},
        )
