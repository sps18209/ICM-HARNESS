"""Harness-owned command execution and acceptance, independent of agent claims."""

from __future__ import annotations

import os
import signal
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import anyio

from icm_harness.evaluation.profile import Check, ProjectProfile
from icm_harness.workspace import candidate_identity, git_revision


def _inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"verification path escapes worktree: {relative}")
    return path


def _junit(path: Path, allow_skips: bool) -> dict:
    if not path.is_file() or path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("missing or oversized JUnit result")
    root = ET.parse(path).getroot()
    if root.tag not in {"testsuite", "testsuites"}:
        raise ValueError("expected JUnit testsuite/testsuites")
    cases = list(root.iter("testcase"))
    failures = sum(case.find("failure") is not None for case in cases)
    errors = sum(case.find("error") is not None for case in cases)
    skipped = sum(case.find("skipped") is not None for case in cases)
    # Suite-level errors must not disappear merely because testcase nodes are absent.
    declared_errors = sum(int(suite.get("errors", "0")) for suite in root.iter("testsuite"))
    declared_failures = sum(int(s.get("failures", "0")) for s in root.iter("testsuite"))
    passed = bool(cases) and not (failures or errors or declared_errors or declared_failures)
    passed = passed and (allow_skips or not skipped) and skipped < len(cases)
    return {
        "passed": passed,
        "total": len(cases),
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
    }


async def _command(check: Check, root: Path, evidence: Path, env: dict) -> dict:
    started = time.monotonic()
    stdout = evidence / f"{check.id}.stdout.log"
    stderr = evidence / f"{check.id}.stderr.log"
    result = {
        "id": check.id,
        "argv": list(check.argv),
        "cwd": check.cwd,
        "passed": False,
        "exit_code": None,
        "result_format": check.result_format,
        "stdout": str(stdout),
        "stderr": str(stderr),
    }
    report = _inside(root, check.report) if check.result_format == "junit" else None
    try:
        # Never accept a stale report from a prior run.
        if report is not None:
            tracked = subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "ls-files",
                    "--error-unmatch",
                    "--",
                    report.relative_to(root.resolve()).as_posix(),
                ],
                capture_output=True,
            )
            if tracked.returncode == 0:
                raise ValueError("JUnit output must not overwrite a tracked product input")
        if report is not None and report.exists():
            report.unlink()
        with stdout.open("wb") as out, stderr.open("wb") as err:
            process = await anyio.open_process(
                list(check.argv),
                cwd=_inside(root, check.cwd),
                env=env,
                stdout=out,
                stderr=err,
                start_new_session=True,
            )
            try:
                with anyio.fail_after(check.timeout_seconds):
                    while process.returncode is None:
                        with anyio.move_on_after(0.1):
                            await process.wait()
                        if stdout.stat().st_size + stderr.stat().st_size > 16 * 1024 * 1024:
                            raise ValueError("command exceeded the 16 MiB log budget")
                    result["exit_code"] = process.returncode
            finally:
                # Stop descendants too, including background processes on a successful
                # command. Services must be supervised by the profile's own lifecycle.
                with anyio.CancelScope(shield=True):
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                        await anyio.sleep(0.05)
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    await process.aclose()
        result["passed"] = result["exit_code"] == 0
        if report is not None:
            result["tests"] = _junit(report, check.allow_skips)
            result["passed"] = result["passed"] and result["tests"]["passed"]
    except (OSError, ValueError, TimeoutError, ET.ParseError) as exc:
        result["passed"] = False
        result["infrastructure_error"] = isinstance(exc, (OSError, TimeoutError))
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["duration_seconds"] = round(time.monotonic() - started, 4)
    result["output_tail"] = {}
    for name, path in (("stdout", stdout), ("stderr", stderr)):
        if path.exists():
            with path.open("rb") as handle:
                handle.seek(max(0, path.stat().st_size - 8000))
                result["output_tail"][name] = handle.read().decode("utf-8", errors="replace")
    return result


async def verify_candidate(
    profile: ProjectProfile,
    root: Path,
    evidence_root: Path,
    cancel_requested=lambda: False,
    total_timeout_seconds: float = 1800,
) -> dict:
    run_id = "verify-" + uuid.uuid4().hex
    evidence = evidence_root / run_id
    evidence.mkdir(parents=True, exist_ok=False)
    before = candidate_identity(root, profile.generated_paths)
    report = {
        "schema_version": 1,
        "run_id": run_id,
        "passed": False,
        "candidate": before,
        "revision": git_revision(root),
        "profile_digest": profile.digest,
        "created_at": datetime.now(UTC).isoformat(),
        "commands": [],
        "requirements": [],
        "failure_class": None,
    }
    env = {name: os.environ[name] for name in profile.inherit_environment if name in os.environ}
    # A dedicated writable area lets tests run while product mutations are detected.
    env["ICM_VERIFICATION_DIR"] = str(evidence)

    async def execute():
        try:
            for phase in ("setup", "reset", "ready", "checks"):
                for check in getattr(profile, phase):
                    entry = await _command(check, root, evidence, env)
                    report["commands"].append({**entry, "phase": phase})
                    if not entry["passed"]:
                        report["failure_class"] = (
                            "implementation"
                            if phase == "checks" and not entry.get("infrastructure_error")
                            else "environment"
                        )
                        return
        finally:
            with anyio.CancelScope(shield=True), anyio.move_on_after(30) as cleanup:
                for check in profile.teardown:
                    entry = await _command(check, root, evidence, env)
                    report["commands"].append({**entry, "phase": "teardown"})
                    if not entry["passed"]:
                        report["failure_class"] = "environment"
            if cleanup.cancel_called:
                report["failure_class"] = "environment"
                report["error"] = "teardown exceeded its 30 second cleanup budget"

    async def watch(scope):
        while True:
            if cancel_requested():
                report["failure_class"] = "cancelled"
                scope.cancel()
                return
            await anyio.sleep(0.1)

    try:
        with anyio.fail_after(total_timeout_seconds):
            async with anyio.create_task_group() as group:
                group.start_soon(watch, group.cancel_scope)
                await execute()
                group.cancel_scope.cancel()
    except TimeoutError:
        report["failure_class"] = "environment"
        report["error"] = "verification exceeded its total time budget"
    after = candidate_identity(root, profile.generated_paths)
    if after != before:
        report["failure_class"] = "candidate_changed"
    outcomes = {
        item["id"]: item["passed"] for item in report["commands"] if item["phase"] == "checks"
    }
    report["requirements"] = [
        {
            **asdict(req),
            "status": "verified"
            if all(outcomes.get(c) for c in req.checks)
            else "failed"
            if any(c in outcomes and not outcomes[c] for c in req.checks)
            else "untested",
        }
        for req in profile.requirements
    ]
    report["passed"] = report["failure_class"] is None and all(
        item["status"] == "verified" for item in report["requirements"]
    )
    return report
