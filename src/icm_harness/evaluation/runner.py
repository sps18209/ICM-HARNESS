"""Provider-neutral verification orchestration; no subprocess or vendor imports."""

from __future__ import annotations

import json
import math
import os
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import anyio

from icm_harness.evaluation.acceptance import decide_acceptance
from icm_harness.kernel.providers import CommandObservation, CommandSpec, EnvironmentSpec
from icm_harness.kernel.verification import Check, ProjectProfile
from icm_harness.ports import VerificationProviders


async def _command(check: Check, handle, providers: VerificationProviders) -> dict:
    try:
        observed = await providers.execution.execute(
            handle,
            CommandSpec(
                check.id,
                check.argv,
                check.cwd,
                check.timeout_seconds,
                check.report if check.result_format != "exit_code" else "",
                tuple(check.attachments),
            ),
        )
    except (OSError, ValueError, TimeoutError) as exc:
        observed = CommandObservation(
            None, 0, "", "", error=f"{type(exc).__name__}: {exc}", infrastructure_error=True
        )
    result = {
        "id": check.id,
        "argv": list(check.argv),
        "cwd": check.cwd,
        "result_format": check.result_format,
        **asdict(observed),
        "passed": observed.exit_code == 0 and not observed.error,
    }
    if check.result_format != "exit_code" and not observed.error:
        try:
            source = await providers.execution.collect(handle, check.report, 10 * 1024 * 1024)
            if providers.evidence is not None:
                try:
                    reference = providers.evidence.put_blob(
                        source,
                        "application/xml" if check.result_format == "junit" else "application/json",
                    )
                except (OSError, ValueError) as exc:
                    result.update(
                        passed=False,
                        infrastructure_error=True,
                        error=f"evidence storage failed: {exc}",
                    )
                    return result
                result["report_blob"] = asdict(reference)
            result["tests"] = providers.verifiers[check.result_format].evaluate(check, source)
            if (
                not isinstance(result["tests"], dict)
                or type(result["tests"].get("passed")) is not bool
            ):
                raise ValueError("verifier must return an explicit boolean passed result")
            result["passed"] = result["passed"] and result["tests"]["passed"]
        except (OSError, ValueError) as exc:
            result.update(
                passed=False,
                error=f"{type(exc).__name__}: {exc}",
                infrastructure_error=isinstance(exc, OSError),
            )
    if check.attachments and not observed.error:
        result["attachments"] = []
        try:
            for path, media_type in check.attachments.items():
                content = await providers.execution.collect(handle, path, 32 * 1024 * 1024)
                reference = providers.evidence.put_blob(content, media_type)
                result["attachments"].append({"path": path, "blob": asdict(reference)})
        except (OSError, ValueError) as exc:
            result.update(passed=False, error=f"required attachment missing or invalid: {exc}")
    return result


async def verify_with_providers(
    profile: ProjectProfile,
    root: str | Path,
    evidence_root: Path,
    cancel_requested=lambda: False,
    total_timeout_seconds: float = 1800,
    *,
    providers: VerificationProviders,
) -> dict:
    if (
        isinstance(total_timeout_seconds, bool)
        or not isinstance(total_timeout_seconds, (int, float))
        or not math.isfinite(total_timeout_seconds)
        or total_timeout_seconds <= 0
    ):
        raise ValueError("verification requires a positive finite total time budget")
    run_id = "verify-" + uuid.uuid4().hex
    evidence = evidence_root / run_id
    evidence.mkdir(parents=True, exist_ok=False)
    candidate = providers.candidate.capture(str(root), profile.generated_paths)
    before = candidate.source_digest
    protected_before = providers.candidate.protected_identity(str(root), profile.protected_paths)
    report = {
        "schema_version": 1,
        "run_id": run_id,
        "passed": False,
        "candidate": before,
        "protected_inputs": protected_before,
        "revision": candidate.revision,
        "profile_digest": profile.digest,
        "created_at": datetime.now(UTC).isoformat(),
        "commands": [],
        "requirements": [],
        "failure_class": None,
    }
    env = {name: os.environ[name] for name in profile.inherit_environment if name in os.environ}
    handle = None
    environment = providers.execution.capabilities()
    report["environment"] = asdict(environment)
    missing = set(profile.required_capabilities) - set(environment.capabilities)
    has_attachments = any(
        check.attachments
        for group in ("checks", "setup", "reset", "ready", "teardown")
        for check in getattr(profile, group)
    )
    if (
        profile.artifact_paths or has_attachments
    ) and "fresh-artifacts" not in environment.capabilities:
        missing.add("fresh-artifacts")
    if profile.artifact_paths and (
        providers.evidence is None
        or not callable(getattr(providers.candidate, "artifact_identity", None))
    ):
        missing.add("artifact-evidence")
    unsupported = {
        check.result_format
        for group in ("checks", "setup", "reset", "ready", "teardown")
        for check in getattr(profile, group)
        if check.result_format != "exit_code" and check.result_format not in providers.verifiers
    }
    if providers.evidence is None and has_attachments:
        missing.add("attachment-evidence-store")
    if missing or unsupported:
        report["failure_class"] = "unsupported_capability"
        report["error"] = (
            f"unsupported capabilities: {sorted(missing)}; verifiers: {sorted(unsupported)}"
        )

    async def execute():
        try:
            for phase in ("setup", "reset", "ready", "checks"):
                if phase == "checks" and profile.artifact_paths:
                    try:
                        report["artifact_digest"] = providers.candidate.artifact_identity(
                            str(root), profile.artifact_paths
                        )
                        report["artifacts"] = []
                        for name in profile.artifact_paths:
                            content = await providers.execution.collect(
                                handle, name, 32 * 1024 * 1024
                            )
                            reference = providers.evidence.put_blob(
                                content, "application/octet-stream"
                            )
                            report["artifacts"].append({"path": name, "blob": asdict(reference)})
                    except (OSError, ValueError) as exc:
                        report.update(
                            failure_class="environment", error=f"artifact capture failed: {exc}"
                        )
                        return
                for check in getattr(profile, phase):
                    entry = await _command(check, handle, providers)
                    report["commands"].append({**entry, "phase": phase})
                    if not entry["passed"]:
                        if report["failure_class"] != "cancelled":
                            report["failure_class"] = (
                                "implementation"
                                if phase == "checks" and not entry.get("infrastructure_error")
                                else "environment"
                            )
                        return
        finally:
            with anyio.CancelScope(shield=True), anyio.move_on_after(30) as cleanup:
                for check in profile.teardown:
                    entry = await _command(check, handle, providers)
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
                try:
                    with anyio.CancelScope(shield=True), anyio.move_on_after(5):
                        await providers.execution.cancel(handle)
                except (OSError, ValueError) as exc:
                    report["failure_class"] = "environment"
                    report["error"] = f"provider cancellation failed: {exc}"
                scope.cancel()
                return
            await anyio.sleep(0.1)

    try:
        if report["failure_class"] is None:
            with anyio.fail_after(total_timeout_seconds):
                handle = await providers.execution.prepare(
                    EnvironmentSpec(
                        str(root),
                        str(evidence),
                        env,
                        profile.required_capabilities,
                        profile.artifact_paths,
                    )
                )
                report["environment"] = asdict(handle.environment)
                async with anyio.create_task_group() as group:
                    group.start_soon(watch, group.cancel_scope)
                    await execute()
                    group.cancel_scope.cancel()
    except TimeoutError:
        report["failure_class"] = "environment"
        report["error"] = "verification exceeded its total time budget"
    except (OSError, ValueError) as exc:
        report["failure_class"] = "environment"
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if handle is not None:
            try:
                with anyio.CancelScope(shield=True), anyio.move_on_after(10) as cleanup:
                    try:
                        await providers.execution.cancel(handle)
                    finally:
                        await providers.execution.close(handle)
            except (OSError, ValueError) as exc:
                report["failure_class"] = "environment"
                report["error"] = f"provider cleanup failed: {exc}"
            if cleanup.cancel_called:
                report["failure_class"] = "environment"
                report["error"] = "provider cleanup exceeded its time budget"
    after = providers.candidate.fingerprint(candidate)
    if after != before:
        report["failure_class"] = "candidate_changed"
    protected_after = providers.candidate.protected_identity(str(root), profile.protected_paths)
    if protected_after != protected_before:
        report["failure_class"] = "evaluator_changed"
    if profile.artifact_paths and report.get("artifact_digest"):
        try:
            if (
                providers.candidate.artifact_identity(str(root), profile.artifact_paths)
                != report["artifact_digest"]
            ):
                report["failure_class"] = "artifact_changed"
        except (OSError, ValueError) as exc:
            report.update(failure_class="artifact_changed", error=f"built artifact changed: {exc}")
    decision = decide_acceptance(profile, report["commands"], report["failure_class"])
    report["requirements"] = list(decision.requirements)
    report["acceptance"] = {"status": decision.status, "reasons": list(decision.reasons)}
    report["passed"] = decision.accepted
    if providers.evidence is not None:
        try:
            snapshot = json.dumps(report, sort_keys=True, allow_nan=False).encode()
            report["receipt"] = asdict(providers.evidence.seal_run(run_id, snapshot))
        except (OSError, ValueError) as exc:
            report.update(
                passed=False, failure_class="environment", error=f"evidence sealing failed: {exc}"
            )
            decision = decide_acceptance(profile, report["commands"], "environment")
            report["acceptance"] = {"status": decision.status, "reasons": list(decision.reasons)}
    return report
