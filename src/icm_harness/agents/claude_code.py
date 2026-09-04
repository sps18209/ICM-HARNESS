"""Stage agent that drives the Claude Code CLI in headless mode.

This lets the Python orchestrator (state, leases, worktree isolation, routing,
bounded retries) use Claude Code as the per-stage worker instead of the Codex CLI.
It shells out to ``claude -p --output-format json`` with the rendered stage prompt
on stdin, then reads the assistant's final message and parses the structured stage
result out of it.

Mutating stages require Claude Code to have file-write permission; set
``permission_mode`` (e.g. ``acceptEdits``) or pass the appropriate flag via
``extra_args`` in ``[agent]`` config. Read-only stages run under the default mode.
"""
from __future__ import annotations

import json
import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass

import anyio

from icm_harness.agents.codex_cli import RESULT_SCHEMA
from icm_harness.agents.contracts import StageInvocation
from icm_harness.agents.errors import StageAgentError, StageCancelled
from icm_harness.agents.prompting import render_stage_prompt
from icm_harness.kernel.contracts import StageResult, StageStatus

_OUTPUT_INSTRUCTION = (
    "\n\nRespond with a SINGLE JSON object and nothing else — no prose, no markdown "
    "code fences — matching exactly this JSON Schema:\n"
    + json.dumps(RESULT_SCHEMA, indent=2, sort_keys=True)
)


def _extract_json_object(text: str) -> str:
    """Return the first complete top-level ``{...}`` object in ``text``.

    Tolerates a model that wraps the object in prose or markdown fences by scanning
    for balanced braces while respecting string literals and escapes.
    """
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ValueError("unterminated JSON object")


@dataclass(frozen=True, slots=True)
class ClaudeCodeStageAgent:
    executable: str = "claude"
    permission_mode: str | None = None
    extra_args: tuple[str, ...] = ()
    inherit_environment: tuple[str, ...] = (
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "TERM",
        "TMPDIR",
        "USER",
    )

    def available(self) -> bool:
        return shutil.which(self.executable) is not None

    def _environment(self) -> Mapping[str, str]:
        return {name: os.environ[name] for name in self.inherit_environment if name in os.environ}

    def _command(self, invocation: StageInvocation) -> list[str]:
        command = [self.executable, "-p", "--output-format", "json"]
        if invocation.model and invocation.model != "default":
            command.extend(("--model", invocation.model))
        if self.permission_mode:
            command.extend(("--permission-mode", self.permission_mode))
        command.extend(self.extra_args)
        return command

    async def run(self, invocation: StageInvocation) -> StageResult:
        if not self.available():
            raise StageAgentError(f"agent executable not found: {self.executable}")
        prompt = render_stage_prompt(invocation) + _OUTPUT_INSTRUCTION
        command = self._command(invocation)

        completed = None
        was_cancelled = False

        async def execute(task_group) -> None:
            nonlocal completed
            completed = await anyio.run_process(
                command,
                input=prompt.encode("utf-8"),
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
            raise StageAgentError((stderr or stdout or f"exit code {completed.returncode}")[-4000:])

        message = self._final_message(stdout)
        try:
            payload = json.loads(_extract_json_object(message))
        except (ValueError, json.JSONDecodeError) as exc:
            raise StageAgentError(
                "agent returned invalid structured output: " + (message[-2000:] or "<empty>")
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
            metadata={"provider": "claude-code", "model": invocation.model or "default"},
        )

    @staticmethod
    def _final_message(stdout: str) -> str:
        """Unwrap Claude Code's ``--output-format json`` envelope to the result text.

        Falls back to the raw stdout when it is not the expected envelope (e.g. a
        text-format response), so the JSON extractor can still find the object.
        """
        try:
            envelope = json.loads(stdout)
        except json.JSONDecodeError:
            return stdout
        if isinstance(envelope, dict) and "result" in envelope:
            if envelope.get("is_error"):
                detail = str(envelope.get("result"))[-2000:]
                raise StageAgentError(f"claude reported an error: {detail}")
            return str(envelope["result"])
        return stdout
