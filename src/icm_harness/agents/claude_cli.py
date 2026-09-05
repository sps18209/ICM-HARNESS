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

# The stage-result contract is provider-agnostic: this adapter reuses the exact
# schema the codex adapter enforces, so a stage produces the same StageResult
# regardless of which coding agent ran it.
#
# Unlike `codex exec`, the `claude` CLI has no `--output-schema` flag, so the
# schema cannot be enforced at the process boundary. Two things stand in for it:
# the schema is appended verbatim to the stdin prompt (see `_render_prompt`),
# and the response is validated against RESULT_SCHEMA's required keys here after
# the fact — an off-contract answer fails the stage closed, exactly as an
# unparseable codex result does.

# The `claude -p --output-format json` envelope wraps the model's final text in
# a `result` field alongside run metadata; the stage-contract JSON is inside it.
_ENVELOPE_RESULT_KEY = "result"

# Auth/config env the `claude` CLI needs to reach a provider. These are
# forwarded IN ADDITION to `inherit_environment`, because the CLI cannot
# authenticate without them and an operator who set the codex-oriented default
# `inherit_environment` would otherwise get a silent auth failure. Everything
# outside this set and `inherit_environment` is still filtered out.
_CLAUDE_AUTH_ENV = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
    "ANTHROPIC_CUSTOM_HEADERS",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CONFIG_DIR",
    "AWS_REGION",
    "AWS_PROFILE",
    "CLOUD_ML_REGION",
)

# Write tools denied to a read-only (non-mutating) stage. The mutation boundary
# is the stage's own `mutates_workspace` flag — the same signal the codex
# adapter turns into a `--sandbox read-only` vs `workspace-write` choice.
# NOTE: unlike codex's OS-level sandbox, denying the write tools does not
# hard-block a shell `>` redirect; the harness's worktree isolation is the
# durable containment, and this is defense in depth over it.
_READ_ONLY_DENIED_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


@dataclass(frozen=True, slots=True)
class ClaudeCLIStageAgent:
    """Runs one harness stage through the `claude` CLI in headless mode.

    Sibling of `CodexCLIStageAgent`: same StageInvocation in, same StageResult
    out, same fail-closed discipline. The provider difference is confined to how
    the subprocess is invoked (`claude -p --output-format json`) and how its
    structured output is recovered (unwrap the envelope's `result`, then parse
    the stage-contract JSON out of it).
    """

    executable: str = "claude"
    extra_args: tuple[str, ...] = ()
    inherit_environment: tuple[str, ...] = ("PATH", "HOME", "TERM", "LANG")
    # A non-mutating stage runs under this permission mode; a mutating one
    # additionally accepts edits. "acceptEdits" auto-approves file edits so the
    # run is non-interactive; an operator can override via extra_args. This
    # deliberately does NOT default to "bypassPermissions".
    permission_mode: str = "acceptEdits"

    def available(self) -> bool:
        return shutil.which(self.executable) is not None

    def _environment(self) -> Mapping[str, str]:
        names = set(self.inherit_environment) | set(_CLAUDE_AUTH_ENV)
        return {name: os.environ[name] for name in names if name in os.environ}

    def _render_prompt(self, invocation: StageInvocation) -> str:
        # `claude` has no --output-schema, so make "the supplied schema" the
        # stage prompt already references real, and pin the output contract.
        schema = json.dumps(RESULT_SCHEMA, indent=2, sort_keys=True)
        return (
            render_stage_prompt(invocation)
            + "\n\nThe supplied schema is:\n"
            + schema
            + "\n\nRespond with ONLY the JSON object that satisfies this schema. "
            "No prose, no explanation, and no Markdown code fences."
        )

    def _command(self, invocation: StageInvocation) -> list[str]:
        command = [
            self.executable,
            "--print",
            "--output-format",
            "json",
            "--permission-mode",
            self.permission_mode,
        ]
        if not invocation.stage.mutates_workspace:
            command.append("--disallowed-tools")
            command.extend(_READ_ONLY_DENIED_TOOLS)
        if invocation.model and invocation.model != "default":
            command.extend(("--model", invocation.model))
        command.extend(self.extra_args)
        return command

    @staticmethod
    def _unwrap_envelope(stdout: str) -> str:
        """Return the model's final text from the CLI's JSON envelope.

        Raises StageAgentError when the CLI reported an error, when the
        envelope is unparseable, or when it carries no textual result.
        """
        try:
            envelope = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise StageAgentError(
                "claude CLI returned a non-JSON envelope: " + (stdout[-2000:] or "<empty>")
            ) from exc
        if not isinstance(envelope, Mapping):
            raise StageAgentError("claude CLI envelope was not a JSON object")
        if envelope.get("is_error") or envelope.get("subtype") not in (None, "success"):
            detail = str(envelope.get(_ENVELOPE_RESULT_KEY) or envelope.get("subtype") or "error")
            raise StageAgentError("claude CLI reported an error: " + detail[-2000:])
        result = envelope.get(_ENVELOPE_RESULT_KEY)
        if not isinstance(result, str) or not result.strip():
            raise StageAgentError("claude CLI envelope carried no textual result")
        return result

    @staticmethod
    def _extract_stage_json(text: str) -> str:
        """Recover the stage-contract JSON object from the model's final text.

        Strips a Markdown code fence if present, else takes the first balanced
        `{...}` span. The model is instructed to emit bare JSON; this only
        salvages the common fence/prose slips rather than trusting them.
        """
        body = text.strip()
        if body.startswith("```"):
            fence_end = body.rfind("```")
            inner = body[3:fence_end] if fence_end > 3 else body[3:]
            if inner.lstrip().lower().startswith("json"):
                inner = inner.lstrip()[4:]
            body = inner.strip()
        if body.startswith("{") and body.endswith("}"):
            return body
        start = body.find("{")
        end = body.rfind("}")
        if start != -1 and end > start:
            return body[start : end + 1]
        return body

    async def run(self, invocation: StageInvocation) -> StageResult:
        if not self.available():
            raise StageAgentError(f"agent executable not found: {self.executable}")
        command = self._command(invocation)
        prompt = self._render_prompt(invocation)

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
            detail = stderr or stdout or f"exit code {completed.returncode}"
            raise StageAgentError(detail[-4000:])

        result_text = self._unwrap_envelope(stdout)
        stage_json = self._extract_stage_json(result_text)
        try:
            payload = json.loads(stage_json)
        except json.JSONDecodeError as exc:
            raise StageAgentError(
                "agent returned invalid structured output: " + (result_text[-2000:] or "<empty>")
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
            metadata={"provider": "claude-cli", "model": invocation.model or "default"},
        )
