"""Provider boundary contracts and actual local-process integration."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

import anyio
import pytest
from verification_support import configure_acceptance, initialize_verified_repo

from icm_harness.adapters.execution.local import LocalExecutionProvider
from icm_harness.adapters.verifiers.junit import JUnitVerifier
from icm_harness.evaluation import (
    load_profile,
    parse_profile,
    verify_candidate,
    verify_with_providers,
)
from icm_harness.kernel.providers import (
    CandidateRef,
    CommandObservation,
    CommandSpec,
    EnvironmentRef,
    EnvironmentSpec,
    ExecutionHandle,
)
from icm_harness.ports import VerificationProviders


class RemoteCandidate:
    def capture(self, locator, generated_paths=()):
        assert locator == "remote://candidate"
        return CandidateRef(locator, "unchanged", "revision", generated_paths)

    def fingerprint(self, ref):
        return ref.source_digest

    def protected_identity(self, locator, paths):
        return "protected"


class RecordingExecution:
    def __init__(self, *, fail=False, cleanup_error=False, wait=False):
        self.calls = []
        self.fail, self.cleanup_error, self.wait = fail, cleanup_error, wait
        self.released = anyio.Event()

    def capabilities(self):
        return EnvironmentRef("recording", "test", "test", "simulation", ("process",))

    async def prepare(self, spec):
        self.calls.append("prepare")
        return ExecutionHandle("remote", self.capabilities())

    async def execute(self, handle, command):
        self.calls.append(command.id)
        if self.fail:
            raise OSError("transport unavailable")
        if self.wait:
            await self.released.wait()
        return CommandObservation(0, 0, "remote://stdout", "remote://stderr")

    async def collect(self, handle, relative, limit):
        return b'<testsuite><testcase classname="api" name="required"/></testsuite>'

    async def cancel(self, handle):
        self.calls.append("cancel")
        self.released.set()

    async def close(self, handle):
        self.calls.append("close")
        if self.cleanup_error:
            raise OSError("cleanup failed")


def remote_profile(tmp_path):
    return parse_profile(configure_acceptance(tmp_path))


@pytest.mark.parametrize("failure", ["none", "transport", "cleanup", "capability"])
def test_provider_orchestration_never_requires_a_local_candidate(tmp_path, monkeypatch, failure):
    profile = remote_profile(tmp_path)
    execution = RecordingExecution(fail=failure == "transport", cleanup_error=failure == "cleanup")
    if failure == "capability":
        profile = replace(profile, required_capabilities=("gpu",))
    providers = VerificationProviders(execution, RemoteCandidate(), {})
    # The orchestrator must never start a host process or invoke Git for this provider.
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("local process leaked"))

    async def scenario():
        return await verify_with_providers(
            profile, "remote://candidate", tmp_path / "evidence", providers=providers
        )

    report = anyio.run(scenario)
    assert report["passed"] is (failure == "none")
    assert report["acceptance"]["status"] == ("accepted" if failure == "none" else "blocked")
    if failure == "capability":
        assert not execution.calls
        assert report["failure_class"] == "unsupported_capability"
    else:
        assert execution.calls[-1] == "close"
        assert "cancel" in execution.calls


def test_report_parsing_is_independent_of_execution_transport(tmp_path):
    payload = configure_acceptance(tmp_path)
    payload["checks"][0].update(
        result_format="junit", report="native.xml", expected_tests=["api::required"]
    )
    execution = RecordingExecution()
    providers = VerificationProviders(execution, RemoteCandidate(), {"junit": JUnitVerifier()})

    async def scenario():
        return await verify_with_providers(
            parse_profile(payload), "remote://candidate", tmp_path / "evidence", providers=providers
        )

    report = anyio.run(scenario)
    assert report["passed"] and report["commands"][0]["tests"]["total"] == 1


def test_cancellation_calls_provider_and_closes_handle(tmp_path):
    execution = RecordingExecution(wait=True)
    providers = VerificationProviders(execution, RemoteCandidate(), {})

    async def scenario():
        return await verify_with_providers(
            remote_profile(tmp_path),
            "remote://candidate",
            tmp_path / "evidence",
            lambda: True,
            providers=providers,
        )

    report = anyio.run(scenario)
    assert not report["passed"] and report["failure_class"] == "cancelled"
    assert execution.calls[-1] == "close" and "cancel" in execution.calls


def test_local_provider_rejects_overlapping_commands_and_closed_handles(tmp_path):
    async def scenario():
        provider = LocalExecutionProvider()
        handle = await provider.prepare(EnvironmentSpec(str(tmp_path), str(tmp_path / "logs"), {}))
        started = anyio.Event()

        async def command():
            started.set()
            await provider.execute(
                handle, CommandSpec("long", (sys.executable, "-c", "import time; time.sleep(10)"))
            )

        async with anyio.create_task_group() as group:
            group.start_soon(command)
            await started.wait()
            with pytest.raises(ValueError, match="active command"):
                await provider.execute(
                    handle, CommandSpec("overlap", (sys.executable, "-c", "pass"))
                )
            group.cancel_scope.cancel()
        await provider.close(handle)
        with pytest.raises(ValueError, match="closed execution handle"):
            await provider.execute(handle, CommandSpec("closed", (sys.executable, "-c", "pass")))
        assert not provider._sessions and not provider._active and not provider._busy

    anyio.run(scenario)


@pytest.mark.parametrize("change", ["path", "report", "timeout", "argv", "id"])
def test_command_contract_rejects_unsafe_values(change):
    kwargs = {"id": "check", "argv": ("python", "-V")}
    kwargs.update(
        {
            "path": {"cwd": "../outside"},
            "report": {"report": "/outside"},
            "timeout": {"timeout_seconds": True},
            "argv": {"argv": "python -V"},
            "id": {"id": "../outside"},
        }[change]
    )
    with pytest.raises(ValueError):
        CommandSpec(**kwargs)


def test_profile_digest_does_not_change_when_no_capability_was_requested(tmp_path):
    profile = remote_profile(tmp_path)
    assert "required_capabilities" not in profile.payload()
    assert parse_profile(profile.payload()).digest == profile.digest


def test_repository_profile_tests_candidate_source_not_installed_checkout(tmp_path):
    initialize_verified_repo(tmp_path)
    repository = Path(__file__).resolve().parents[1]
    shutil.copytree(
        repository / "src", tmp_path / "src", ignore=shutil.ignore_patterns("__pycache__")
    )
    package = tmp_path / "src/icm_harness/__init__.py"
    package.write_text(package.read_text() + "\nCANDIDATE_MARKER = True\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_binding.py").write_text(
        "import icm_harness\n"
        "def test_candidate():\n"
        "    assert getattr(icm_harness, 'CANDIDATE_MARKER', False)\n"
    )
    payload = configure_acceptance(tmp_path)
    check = asdict(load_profile(repository).checks[0])
    check.update(
        id="fixture", expected_tests=["tests/test_binding.py::test_candidate"], optional_skips={}
    )
    payload["checks"] = [check]
    payload["inherit_environment"] = ["PATH", "HOME", "PYTHONPATH"]
    report = anyio.run(
        verify_candidate, parse_profile(payload), tmp_path, tmp_path / ".harness/rounds"
    )
    assert report["passed"], report["commands"]


def test_library_round_succeeds_without_operator_or_cli_provider_modules(tmp_path):
    initialize_verified_repo(tmp_path)
    script = r"""
import importlib.abc, json, sys
from pathlib import Path
class NoInterfaces(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("icm_harness.cli", "icm_harness.mcp", "icm_harness.web",
                               "icm_harness.agents.codex_cli", "icm_harness.agents.claude_cli")):
            raise ImportError("interface unavailable: " + fullname)
sys.meta_path.insert(0, NoInterfaces())
import anyio
from icm_harness.application import build_application
from icm_harness.kernel.contracts import StageResult, StageStatus, TaskIntent, TaskProfile
class Agent:
    async def run(self, inv):
        return StageResult(StageStatus.PASS, "deterministic fixture", artifacts={
            name: "{}" if name.endswith(".json") else "# fixture"
            for name in inv.stage.required_outputs})
app = build_application(Path.cwd(), agent=Agent())
rec = app.create_round(TaskProfile("check fixture", intent=TaskIntent.QUICK))
result = anyio.run(app.run_round, rec.round_id)
assert result.status == "closed", result.last_error
evidence = [e.payload for e in app.events(rec.round_id) if e.kind == "candidate_verified"]
assert evidence and evidence[-1]["passed"]
print(json.dumps({"status": result.status, "provider": evidence[-1]["environment"]["provider"]}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"status": "closed", "provider": "local"}
