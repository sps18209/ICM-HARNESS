"""Sandboxed command execution adapter (E2B).

Runs shell commands inside an ephemeral E2B sandbox. Raises
:class:`IntegrationUnavailable` when the E2B SDK is not installed. Used by the
workspace/execution layers when a stage must run untrusted commands off-host.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class E2BSandboxConfig:
    template: str | None = None
    timeout_seconds: int = 1800


@dataclass(frozen=True, slots=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str


def _require_e2b():
    try:
        from e2b_code_interpreter import Sandbox
    except ImportError as exc:
        from icm_harness.kernel.errors import IntegrationUnavailable

        raise IntegrationUnavailable(
            "Install E2B: pip install e2b-code-interpreter"
        ) from exc
    return Sandbox


class E2BSandboxRunner:
    def __init__(self, config: E2BSandboxConfig | None = None):
        self.config = config or E2BSandboxConfig()

    def run(self, command: str) -> SandboxResult:
        sandbox_cls = _require_e2b()
        kwargs = {"timeout": self.config.timeout_seconds}
        if self.config.template:
            kwargs["template"] = self.config.template
        with sandbox_cls.create(**kwargs) as sandbox:
            execution = sandbox.commands.run(command)
            return SandboxResult(
                exit_code=getattr(execution, "exit_code", 0),
                stdout=getattr(execution, "stdout", ""),
                stderr=getattr(execution, "stderr", ""),
            )
