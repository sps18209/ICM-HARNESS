from __future__ import annotations

import json
import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import anyio

from icm_harness.agents.contracts import StageInvocation
from icm_harness.agents.errors import StageAgentError, StageCancelled
from icm_harness.agents.prompting import render_stage_prompt
from icm_harness.kernel.contracts import StageResult, StageStatus

RESULT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["status", "summary", "artifacts", "trigger_codes"],
    "properties": {
        "status": {
            "type": "string",
            "enum": ["pass", "fail", "blocked", "retryable", "cancelled"],
        },
        "summary": {"type": "string"},
        "artifacts": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
        "return_to": {"type": ["string", "null"]},
        "trigger_codes": {"type": "array", "items": {"type": "string"}},
    },
}


@dataclass(frozen=True, slots=True)
class CodexCLIStageAgent:
    executable: str = "codex"
    extra_args: tuple[str, ...] = ()
    inherit_environment: tuple[str, ...] = ("PATH", "HOME", "CODEX_HOME")

    def available(self) -> bool:
        return shutil.which(self.executable) is not None

    def _schema_path(self, workspace: Path) -> Path:
        path = workspace / ".harness/runtime/stage-result.schema.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        expected = json.dumps(RESULT_SCHEMA, indent=2, sort_keys=True) + "\n"
        if not path.exists() or path.read_text(encoding="utf-8") != expected:
            path.write_text(expected, encoding="utf-8")
        return path

    def _environment(self) -> Mapping[str, str]:
        return {name: os.environ[name] for name in self.inherit_environment if name in os.environ}

    async def run(self, invocation: StageInvocation) -> StageResult:
        if not self.available():
            raise StageAgentError(f"agent executable not found: {self.executable}")
        schema = self._schema_path(invocation.workspace)
        sandbox = "workspace-write" if invocation.stage.mutates_workspace else "read-only"
        command = [
            self.executable,
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            sandbox,
            "--color",
            "never",
            "--output-schema",
            str(schema),
        ]
        if invocation.model and invocation.model != "default":
            command.extend(("--model", invocation.model))
        command.extend(self.extra_args)
        command.append("-")

        completed = None
        was_cancelled = False

        async def execute(task_group) -> None:
            nonlocal completed
            completed = await anyio.run_process(
                command,
                input=render_stage_prompt(invocation).encode("utf-8"),
                cwd=invocation.workspace,
                env=self._environment(),
                check=False,
            )
            task_group.cancel_scope.cancel()

        async def watch_cancel(task_group) -> None:
            nonlocal was_cancelled
            while True:
                await anyio.sleep(0.25)
                if invocation.cancel_requested():
                    was_cancelled = True
                    task_group.cancel_scope.cancel()
                    return

        async with anyio.create_task_group() as task_group:
            task_group.start_soon(execute, task_group)
            task_group.start_soon(watch_cancel, task_group)
        if was_cancelled:
            raise StageCancelled(f"round {invocation.round_id} was cancelled")
        if completed is None:
            raise StageAgentError("agent process ended without a result")

        stdout = completed.stdout.decode("utf-8", errors="replace").strip()
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        if completed.returncode != 0:
            detail = stderr or stdout or f"exit code {completed.returncode}"
            raise StageAgentError(detail[-4000:])
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise StageAgentError(
                "agent returned invalid structured output: " + (stdout[-2000:] or "<empty>")
            ) from exc
        try:
            status = StageStatus(payload["status"])
            summary = str(payload["summary"])
            artifacts = {str(k): str(v) for k, v in payload.get("artifacts", {}).items()}
            return_to = payload.get("return_to")
            trigger_codes = tuple(str(value) for value in payload.get("trigger_codes", ()))
        except (KeyError, TypeError, ValueError) as exc:
            raise StageAgentError(f"agent result violates the stage contract: {exc}") from exc
        return StageResult(
            status,
            summary,
            artifacts=artifacts,
            return_to=return_to,
            trigger_codes=trigger_codes,
            metadata={"provider": "codex-cli", "model": invocation.model or "default"},
        )
