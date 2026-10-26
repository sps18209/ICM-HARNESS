from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from icm_harness.agents import (
    DryRunStageAgent,
    StageAgent,
    StageCancelled,
    StageInvocation,
    make_stage_agent,
)
from icm_harness.application.artifacts import ArtifactStore
from icm_harness.config import HarnessConfig, load_config
from icm_harness.context import (
    ContextBudget,
    ContextEngine,
    ContextTrigger,
    FilesystemWikiProvider,
    estimate_tokens,
)
from icm_harness.evaluation import (
    load_profile,
    local_verification_providers,
    parse_profile,
    require_stage_outputs,
    verify_candidate,
)
from icm_harness.execution import (
    KeyedLimiter,
    LeaseHeartbeat,
    LocalExecutor,
    ManagedStageExecutor,
    SQLiteRunStore,
)
from icm_harness.kernel.contracts import (
    ContextItem,
    ModelCandidate,
    ModelRequest,
    StageResult,
    StageStatus,
    TaskIntent,
    TaskProfile,
)
from icm_harness.kernel.lifecycle import RoundController
from icm_harness.kernel.providers import EvidenceRef
from icm_harness.kernel.state import ArtifactRecord, EventRecord, RoundRecord, SQLiteStateStore
from icm_harness.modes import get_stage, stage_refs_for_route
from icm_harness.observability import AuditEvent, JsonlAuditSink
from icm_harness.policies import AuthorizationPolicy, SituationalSettingsPolicy
from icm_harness.ports import VerificationProviders
from icm_harness.routing import (
    BayesianPerformanceStore,
    HeuristicCorrelation,
    ModelRouter,
    ModeRouter,
)
from icm_harness.workspace import (
    GitWorktreeManager,
    artifact_identity,
    candidate_identity,
    file_lock,
    git_revision,
    protected_identity,
)

TERMINAL_ROUND_STATUSES = frozenset({"closed", "failed", "cancelled"})


class HarnessApplication:
    """Composition root shared by the CLI, HTTP API, and background workers."""

    def __init__(
        self,
        root: str | Path,
        *,
        config: HarnessConfig | None = None,
        agent: StageAgent | None = None,
        dry_run: bool = False,
        verification_providers: VerificationProviders | None = None,
    ):
        self.verification_providers = verification_providers
        self.root = Path(root).resolve()
        self.config = config or load_config(self.root)
        state_path = self.root / self.config.runtime.state_db
        self.state = SQLiteStateStore(state_path)
        self.controller = RoundController(
            self.state,
            get_stage=get_stage,
            stage_refs_for_route=stage_refs_for_route,
        )
        self.runs = SQLiteRunStore(state_path)
        self.executor = ManagedStageExecutor(
            LocalExecutor(self.state, KeyedLimiter(self.config.runtime.global_concurrency)),
            self.runs,
        )
        self.artifacts = ArtifactStore(self.root, self.state)
        self.audit = JsonlAuditSink(self.root / self.config.runtime.audit_log)
        self.context = ContextEngine([FilesystemWikiProvider(self.root / "0_Context_Wiki")])
        self.settings_policy = SituationalSettingsPolicy()
        self.performance = BayesianPerformanceStore(
            self.root / ".harness/runtime/model-performance.sqlite3"
        )
        self.agent = agent or make_stage_agent(self.config.agent, dry_run=dry_run)
        self.dry_run = dry_run or isinstance(self.agent, DryRunStageAgent)

    def create_round(self, profile: TaskProfile) -> RoundRecord:
        route = ModeRouter().route(profile)
        captured = None
        if (
            not self.dry_run
            and any(mode.value in {"build", "quick"} for mode in route.modes)
            and (self.root / ".harness/project.json").exists()
        ):
            # Missing profiles remain visible/blocking at verification, so planning is
            # still usable. An invalid present profile fails before any agent runs.
            captured = load_profile(self.root).payload()
        record = self.controller.create(profile, route)
        protected = (
            protected_identity(self.root, parse_profile(captured).protected_paths)
            if captured
            else None
        )
        self._event(
            record.round_id,
            "project_profile_captured",
            None,
            {"profile": captured, "protected_digest": protected},
        )
        self._write_current(record.round_id)
        self._event(
            record.round_id,
            "round_created",
            record.current_stage,
            {
                "route": list(record.route),
                "reason": route.reason,
                "profile": dict(record.profile or {}),
            },
        )
        return record

    def get_round(self, round_id: str) -> RoundRecord:
        return self.state.get_round(round_id)

    def list_rounds(self, *, limit: int = 100) -> tuple[RoundRecord, ...]:
        return self.state.list_rounds(limit=limit)

    def current_round(self) -> RoundRecord | None:
        path = self.root / "2_Working_State/CURRENT"
        if not path.exists():
            return None
        round_id = path.read_text(encoding="utf-8").strip()
        if not round_id or round_id == "NONE":
            return None
        return self.state.get_round(round_id)

    def events(self, round_id: str, *, after_id: int = 0) -> tuple[EventRecord, ...]:
        return self.state.list_events(round_id, after_id=after_id)

    def list_artifacts(self, round_id: str) -> tuple[ArtifactRecord, ...]:
        return self.state.list_artifacts(round_id)

    def read_artifact(self, artifact_id: int) -> tuple[ArtifactRecord, str]:
        record = self.state.get_artifact(artifact_id)
        return record, self.artifacts.read(record)

    def diff_round(self, round_id: str) -> str:
        record = self.state.get_round(round_id)
        if not record.workspace_path:
            return ""
        return GitWorktreeManager(self.root, self.config.workspace.worktree_root).diff(
            record.workspace_path
        )

    def approve_promotion(self, round_id: str) -> RoundRecord:
        """Record explicit human approval to merge a closed round's worktree.

        This is a distinct, separately-audited step from *running* the round: the merge is a
        human gate (``AuthorizationPolicy.require_human_approval_for_merge``), so it must not
        happen as an implicit side effect of ``run_round``. ``promote_round`` refuses to merge
        until this approval has been recorded.
        """
        record = self.state.get_round(round_id)
        if record.status != "closed":
            raise ValueError(f"round {round_id} must be closed before its promotion is approved")
        if not record.workspace_path:
            raise ValueError(f"round {round_id} has no isolated workspace to promote")
        if any(event.kind == "round_promoted" for event in self.state.list_events(round_id)):
            raise ValueError(f"round {round_id} was already promoted")
        identity = self._accepted_candidate(record)
        self._promotion_review(record)
        self._event(round_id, "merge_approved", None, identity)
        return self.state.get_round(round_id)

    def _merge_is_approved(self, round_id: str) -> bool:
        identity = self._accepted_candidate(self.state.get_round(round_id))
        approvals = [e for e in self.state.list_events(round_id) if e.kind == "merge_approved"]
        return bool(approvals) and approvals[-1].payload == identity

    def promote_round(self, round_id: str) -> RoundRecord:
        record = self.state.get_round(round_id)
        if record.status != "closed":
            raise ValueError(f"round {round_id} must be closed before promotion")
        if not record.workspace_path:
            raise ValueError(f"round {round_id} has no isolated workspace to promote")
        if any(event.kind == "round_promoted" for event in self.state.list_events(round_id)):
            raise ValueError(f"round {round_id} was already promoted")
        if not self._merge_is_approved(round_id):
            raise ValueError(
                f"round {round_id} requires explicit promotion approval before merge — "
                "call approve_promotion (icm approve-merge / icm_approve_promotion) first"
            )
        identity = self._accepted_candidate(record)
        profile = self._project_profile(round_id)
        with file_lock(self.root / ".harness/runtime/promotion.lock"):
            if self._accepted_candidate(record) != identity:
                raise ValueError("verified candidate changed while waiting for promotion")
            commit = GitWorktreeManager(self.root, self.config.workspace.worktree_root).promote(
                record.workspace_path,
                message=f"ICM round {round_id}: {record.objective}",
                expected_candidate=identity["candidate"],
                expected_base=identity["base_revision"],
                generated_paths=profile.generated_paths,
                artifact_paths=profile.artifact_paths,
                expected_artifact_digest=identity.get("artifact_digest"),
            )
        promoted = {"commit": commit}
        if profile.artifact_paths:
            promoted.update(
                artifact_digest=identity["artifact_digest"], verification_run_id=identity["run_id"]
            )
        self._event(round_id, "round_promoted", None, promoted)
        return self.state.get_round(round_id)

    def _project_profile(self, round_id: str):
        for event in self.events(round_id):
            if event.kind == "project_profile_captured" and event.payload.get("profile"):
                return parse_profile(event.payload["profile"])
        raise ValueError(
            "No captured acceptance profile. Configure .harness/project.json "
            "and create a new round."
        )

    def _require_protected(self, round_id: str, workspace: Path) -> None:
        profile = self._project_profile(round_id)
        captured = next(e for e in self.events(round_id) if e.kind == "project_profile_captured")
        if protected_identity(workspace, profile.protected_paths) != captured.payload.get(
            "protected_digest"
        ):
            raise ValueError("protected acceptance inputs changed; create a reviewed new round")

    def _accepted_candidate(self, record: RoundRecord) -> dict:
        if self.dry_run:
            raise ValueError("simulated rounds cannot be promoted")
        profile = self._project_profile(record.round_id)
        events = [e for e in self.events(record.round_id) if e.kind == "candidate_verified"]
        if not events or not events[-1].payload.get("passed"):
            raise ValueError("candidate has no passing executable verification")
        report = events[-1].payload
        if report.get("receipt"):
            providers = self.verification_providers or local_verification_providers(
                self.artifacts.round_root / record.round_id / "verification"
            )
            if providers.evidence is None:
                raise ValueError("verification evidence store is unavailable")
            sealed = providers.evidence.get_blob(EvidenceRef(**report["receipt"]))
            expected = {k: v for k, v in report.items() if k not in {"receipt", "base_revision"}}
            if json.loads(sealed) != json.loads(json.dumps(expected)):
                raise ValueError("verification receipt does not match accepted evidence")
            for command in report["commands"]:
                if command.get("report_blob"):
                    providers.evidence.get_blob(EvidenceRef(**command["report_blob"]))
                for attachment in command.get("attachments", []):
                    providers.evidence.get_blob(EvidenceRef(**attachment["blob"]))
            for artifact in report.get("artifacts", []):
                providers.evidence.get_blob(EvidenceRef(**artifact["blob"]))
        workspace = Path(record.workspace_path) if record.workspace_path else self.root
        self._require_protected(record.round_id, workspace)
        if candidate_identity(workspace, profile.generated_paths) != report["candidate"]:
            raise ValueError("candidate changed after verification; run a new round")
        if profile.artifact_paths and (
            not report.get("artifact_digest")
            or artifact_identity(workspace, profile.artifact_paths) != report["artifact_digest"]
        ):
            raise ValueError("built artifact changed after verification; run a new round")
        if git_revision(self.root) != report["base_revision"]:
            raise ValueError(
                "destination changed after verification; create a round on the new base"
            )
        identity = {
            key: report[key] for key in ("candidate", "base_revision", "profile_digest", "run_id")
        }
        if profile.artifact_paths:
            identity["artifact_digest"] = report["artifact_digest"]
        return identity

    def _handoff(self, record: RoundRecord) -> str:
        sections = [f"Original objective: {record.objective}"]
        try:
            profile = self._project_profile(record.round_id)
            sections.append(
                "Captured acceptance/environment contract:\n"
                + json.dumps(profile.payload(), indent=2)
            )
        except ValueError:
            sections.append("No captured project acceptance profile; actual acceptance is blocked.")
        for artifact in self.list_artifacts(record.round_id):
            if artifact.stage_ref == record.current_stage:
                continue
            text = self.artifacts.read(artifact)
            reference = self.root / artifact.relative_path
            sections.append(
                f"Prior artifact {artifact.stage_ref}/{artifact.name}; SHA256 {artifact.sha256}; "
                f"full content: {reference}\n{text[:12000]}"
                + (
                    "\n[Excerpt only: read the referenced file before relying on it.]"
                    if len(text) > 12000
                    else ""
                )
            )
        failures = [e for e in self.events(record.round_id) if e.kind == "candidate_verified"]
        if failures:
            latest = failures[-1].payload
            brief = {
                key: latest.get(key)
                for key in (
                    "run_id",
                    "passed",
                    "candidate",
                    "failure_class",
                    "requirements",
                    "error",
                )
            }
            brief["failed_commands"] = [
                {
                    **{
                        k: command.get(k)
                        for k in ("id", "argv", "exit_code", "error", "stdout", "stderr")
                    },
                    "output_tail": {
                        k: value[-2000:] for k, value in command.get("output_tail", {}).items()
                    },
                }
                for command in latest.get("commands", [])
                if not command["passed"]
            ][:4]
            sections.append(
                "Most recent harness verification (summary; full logs at referenced paths):\n"
                + json.dumps(brief, indent=2)
            )
        return "\n\n".join(sections)

    def approve_round(self, round_id: str) -> RoundRecord:
        record = self.state.get_round(round_id)
        if record.status != "waiting_approval" or not record.active_gate:
            raise ValueError(f"round {round_id} is not waiting for approval")
        stage_ref = record.active_gate
        self._event(round_id, "gate_approved", stage_ref, {"stage": stage_ref})
        return self.state.set_status(round_id, "active")

    def cancel_round(self, round_id: str) -> RoundRecord:
        record = self.state.request_cancel(round_id)
        self._event(round_id, "cancel_requested", record.current_stage, {})
        if record.status != "running":
            record = self.state.set_status(round_id, "cancelled")
            self._clear_current_if(round_id)
        return record

    def retry_round(self, round_id: str) -> RoundRecord:
        record = self.state.get_round(round_id)
        if record.status not in {"failed", "blocked", "cancelled"}:
            raise ValueError(f"round {round_id} is not retryable from status {record.status}")
        self.state.clear_cancel(round_id)
        record = self.state.set_status(round_id, "active")
        self._write_current(round_id)
        self._event(round_id, "round_retried", record.current_stage, {})
        return record

    async def run_round(self, round_id: str) -> RoundRecord:
        owner = f"runner-{uuid.uuid4().hex[:12]}"
        lease_key = f"round:{round_id}:runner"
        async with LeaseHeartbeat(
            self.state,
            lease_key,
            owner,
            self.config.runtime.lease_ttl_seconds,
            self.config.runtime.heartbeat_seconds,
        ):
            return await self._run_round_owned(round_id, owner)

    async def _run_round_owned(self, round_id: str, owner: str) -> RoundRecord:
        record = self.state.get_round(round_id)
        if record.status == "closed":
            return record
        if record.cancel_requested:
            self._clear_current_if(round_id)
            return self.state.set_status(round_id, "cancelled")
        if record.status == "waiting_approval":
            return record
        if record.status in {"failed", "blocked", "cancelled"}:
            raise ValueError(f"round {round_id} must be retried before it can run")

        self.state.set_status(round_id, "running")
        self._event(round_id, "round_started", record.current_stage, {"owner": owner})
        transitions = 0

        while transitions < self.config.runtime.max_stage_transitions:
            record = self.state.get_round(round_id)
            if record.cancel_requested:
                self._event(round_id, "round_cancelled", record.current_stage, {})
                self._clear_current_if(round_id)
                return self.state.set_status(round_id, "cancelled")
            if record.current_stage is None:
                self._event(round_id, "round_completed", None, {})
                self._clear_current_if(round_id)
                return record

            stage = get_stage(record.current_stage)
            if stage.requires_human_gate and not self._gate_is_approved(round_id, stage.ref):
                self._event(
                    round_id,
                    "gate_waiting",
                    stage.ref,
                    {"message": f"Approval required before {stage.ref}"},
                )
                return self.state.set_status(
                    round_id,
                    "waiting_approval",
                    active_gate=stage.ref,
                )

            try:
                result = await self._run_stage(record, owner)
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"[-4000:]
                self._event(round_id, "round_failed", record.current_stage, {"error": message})
                return self.state.set_status(round_id, "failed", last_error=message)
            transitions += 1
            if result.status is StageStatus.PASS:
                continue
            return self.state.get_round(round_id)

        message = f"round exceeded {self.config.runtime.max_stage_transitions} stage transitions"
        self._event(round_id, "round_failed", record.current_stage, {"error": message})
        return self.state.set_status(round_id, "failed", last_error=message)

    async def _run_stage(self, record: RoundRecord, owner: str) -> StageResult:
        stage = get_stage(record.current_stage or "")
        profile = self._profile(record)
        previous = [e for e in self.events(record.round_id) if e.kind == "stage_completed"]
        known_triggers = {trigger.value: trigger for trigger in ContextTrigger}
        triggers = tuple(
            known_triggers[code]
            for code in (previous[-1].payload.get("triggers", []) if previous else [])
            if code in known_triggers
        )
        settings = self.settings_policy.settings(
            stage.ref,
            stakes=profile.stakes,
            triggers=triggers,
        )
        workspace = self._workspace_for(record, stage.mutates_workspace)
        artifact_dir = self.artifacts.stage_dir(record.round_id, stage.ref)
        context = self._context_for(profile, stage.ref, settings.context_tier, triggers)
        handoff = self._handoff(record)
        model_name, model_payload = self._select_model(
            record.round_id,
            profile,
            stage.ref,
            context.used_tokens + estimate_tokens(handoff),
            settings,
        )
        model_payload["handoff_tokens"] = estimate_tokens(handoff)
        self._event(record.round_id, "model_selected", stage.ref, model_payload)

        authorization = AuthorizationPolicy(
            allow_shell=True,
            allow_network=settings.allow_network_tools,
            allow_production_write=False,
            allow_secret_access=False,
            require_human_approval_for_merge=True,
        )
        max_attempts = self.config.runtime.max_attempts
        last_result = StageResult(StageStatus.FAIL, "stage did not run")

        for attempt in range(1, max_attempts + 1):
            latest = self.state.get_round(record.round_id)
            if latest.cancel_requested:
                last_result = StageResult(StageStatus.CANCELLED, "cancelled by operator")
                break
            invocation = StageInvocation(
                record.round_id,
                profile,
                stage,
                context,
                settings,
                workspace,
                artifact_dir,
                model_name,
                attempt,
                authorization,
                lambda: self.state.get_round(record.round_id).cancel_requested,
                handoff,
            )
            self._event(
                record.round_id,
                "stage_started",
                stage.ref,
                {
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "workspace": str(workspace),
                    "context_tier": context.tier,
                    "context_tokens": context.used_tokens,
                },
            )
            try:
                frozen = None
                if (
                    not self.dry_run
                    and not stage.mutates_workspace
                    and (
                        record.workspace_path
                        or stage.ref
                        in {"build.tester", "build.close", "quick.verify", "quick.close"}
                    )
                ):
                    frozen = candidate_identity(workspace)
                last_result = await self.executor.run(
                    lambda invocation=invocation: self.agent.run(invocation),
                    round_id=record.round_id,
                    stage_ref=stage.ref,
                    resource_key=self._resource_key(stage.ref, workspace, stage.mutates_workspace),
                    owner=f"{owner}:{stage.ref}:{attempt}",
                    timeout_seconds=self.config.runtime.stage_timeout_seconds,
                    max_attempts=max_attempts,
                    attempt=attempt,
                )
                if frozen is not None and candidate_identity(workspace) != frozen:
                    raise ValueError("non-mutating stage changed product inputs")
                if "verification.json" in last_result.artifacts:
                    raise ValueError("verification.json is reserved for harness-owned evidence")
                if last_result.status is StageStatus.PASS:
                    missing = [
                        name
                        for name in stage.required_outputs
                        if not last_result.artifacts.get(name, "").strip()
                    ]
                    if missing:
                        raise ValueError(
                            "missing required outputs in current attempt: " + ", ".join(missing)
                        )
                written = self.artifacts.write_many(
                    record.round_id,
                    stage.ref,
                    dict(last_result.artifacts),
                )
                if written:
                    self._event(
                        record.round_id,
                        "artifacts_written",
                        stage.ref,
                        {
                            "artifact_ids": [item.id for item in written],
                            "names": [item.name for item in written],
                        },
                    )
                if last_result.status is StageStatus.PASS:
                    require_stage_outputs(stage, artifact_dir)
                    if not self.dry_run and stage.ref in {"build.tester", "quick.verify"}:
                        try:
                            profile_contract = self._project_profile(record.round_id)
                        except ValueError as exc:
                            last_result = StageResult(StageStatus.BLOCKED, str(exc))
                        else:
                            self._require_protected(record.round_id, workspace)
                            base_revision = git_revision(self.root)
                            origins = [
                                e
                                for e in self.events(record.round_id)
                                if e.kind == "workspace_created"
                            ]
                            if (
                                origins
                                and origins[-1].payload.get("base_revision") != base_revision
                            ):
                                raise ValueError("destination moved since worktree creation")
                            report = await verify_candidate(
                                profile_contract,
                                workspace,
                                self.artifacts.round_root / record.round_id / "verification",
                                invocation.cancel_requested,
                                total_timeout_seconds=self.config.runtime.stage_timeout_seconds,
                                providers=self.verification_providers,
                            )
                            report["base_revision"] = base_revision
                            if git_revision(self.root) != base_revision:
                                report.update(passed=False, failure_class="environment")
                            self.artifacts.write_many(
                                record.round_id,
                                stage.ref,
                                {
                                    "verification.json": json.dumps(report, indent=2),
                                },
                            )
                            self._event(record.round_id, "candidate_verified", stage.ref, report)
                            if not report["passed"]:
                                cause = report["failure_class"]
                                if cause == "implementation":
                                    writer_ref = (
                                        "build.writer"
                                        if stage.ref == "build.tester"
                                        else "quick.execute"
                                    )
                                    self._model_feedback(
                                        self._writer_model(record.round_id), writer_ref, False
                                    )
                                status = (
                                    StageStatus.CANCELLED
                                    if cause == "cancelled"
                                    else StageStatus.BLOCKED
                                    if cause in {"environment", "unsupported_capability"}
                                    else StageStatus.FAIL
                                )
                                target = (
                                    "build.writer"
                                    if stage.ref == "build.tester" and cause == "implementation"
                                    else None
                                )
                                last_result = StageResult(
                                    status,
                                    f"Executable verification failed: {cause}",
                                    return_to=target,
                                    trigger_codes=("test_failure_plan",),
                                )
                            else:
                                self._model_feedback(
                                    self._writer_model(record.round_id),
                                    "build.writer"
                                    if stage.ref == "build.tester"
                                    else "quick.execute",
                                    True,
                                )
                    if not self.dry_run and stage.ref in {"build.close", "quick.close"}:
                        self._accepted_candidate(self.state.get_round(record.round_id))
                    self._semantic_gate(record, stage.ref, dict(last_result.artifacts))
                self._event(
                    record.round_id,
                    "stage_completed",
                    stage.ref,
                    {
                        "attempt": attempt,
                        "status": last_result.status.value,
                        "summary": last_result.summary,
                        "return_to": last_result.return_to,
                        "triggers": list(last_result.trigger_codes),
                    },
                )
            except StageCancelled:
                last_result = StageResult(StageStatus.CANCELLED, "cancelled by operator")
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                self._event(
                    record.round_id,
                    "stage_attempt_failed",
                    stage.ref,
                    {"attempt": attempt, "error": message[-4000:]},
                )
                if attempt < max_attempts:
                    continue
                self._model_feedback(model_name, stage.ref, False)
                self.state.set_status(record.round_id, "failed", last_error=message[-4000:])
                return StageResult(StageStatus.FAIL, message)

            if last_result.status is StageStatus.RETRYABLE and attempt < max_attempts:
                continue
            break

        if last_result.status is StageStatus.PASS:
            self.controller.complete_stage(record.round_id, last_result)
            if stage.ref not in {"build.writer", "quick.execute"}:
                self._model_feedback(model_name, stage.ref, True)
            return last_result
        if last_result.status is StageStatus.CANCELLED:
            self.state.set_status(record.round_id, "cancelled", last_error=last_result.summary)
            self._clear_current_if(record.round_id)
            return last_result
        if last_result.return_to:
            self.controller.complete_stage(record.round_id, last_result)
            self.state.set_status(record.round_id, "running")
            self._model_feedback(model_name, stage.ref, False)
            return StageResult(StageStatus.PASS, f"returned to {last_result.return_to}")
        target_status = "blocked" if last_result.status is StageStatus.BLOCKED else "failed"
        self.state.set_status(record.round_id, target_status, last_error=last_result.summary)
        self._model_feedback(model_name, stage.ref, False)
        return last_result

    def _semantic_gate(self, record: RoundRecord, stage_ref: str, outputs: dict[str, str]) -> None:
        """Advisory Jev grading of a passing stage's outputs (typesafe-jev.md
        point 2). It records events for humans and reward attribution — it can
        never fail the stage, and any adapter error degrades to an event."""
        if self.dry_run or self.config.evaluation.semantic_gate != "typesafe" or not outputs:
            return
        try:
            from icm_harness.integrations.typesafe import review_stage_outputs

            review = review_stage_outputs(record.objective, stage_ref, outputs)
            self._event(
                record.round_id,
                "semantic_gate",
                stage_ref,
                {**review.as_payload(), "concerns": list(review.concerns())},
            )
        except Exception as exc:  # noqa: BLE001 — advisory review, never a gate
            self._event(
                record.round_id,
                "semantic_gate_unavailable",
                stage_ref,
                {"error": f"{type(exc).__name__}: {exc}"[-500:]},
            )

    def _promotion_review(self, record: RoundRecord) -> None:
        """Advisory Jev sweep of the round diff before merge approval
        (typesafe-jev.md point 3, backing ADR-0010). A red flag may only add
        scrutiny — the human approval that follows stays the authority, and
        any adapter error degrades to an event."""
        if self.dry_run or self.config.evaluation.promotion_review != "typesafe":
            return
        try:
            from icm_harness.integrations.typesafe import review_diff

            diff = self.diff_round(record.round_id)
            if not diff:
                return
            review = review_diff(record.objective, diff)
            self._event(
                record.round_id,
                "promotion_reviewed",
                None,
                {
                    **review.as_payload(),
                    "concerns": list(review.concerns()),
                    "suggested_approval_class": review.suggested_approval_class().value,
                },
            )
        except Exception as exc:  # noqa: BLE001 — advisory review, never a gate
            self._event(
                record.round_id,
                "promotion_review_unavailable",
                None,
                {"error": f"{type(exc).__name__}: {exc}"[-500:]},
            )

    def _workspace_for(self, record: RoundRecord, mutates: bool) -> Path:
        if self.dry_run:
            return self.root
        if record.workspace_path:
            path = Path(record.workspace_path)
            if not path.exists():
                raise FileNotFoundError(f"round worktree no longer exists: {path}")
            return path
        if not mutates or self.config.workspace.strategy == "in_place":
            return self.root
        manager = GitWorktreeManager(self.root, self.config.workspace.worktree_root)
        base_revision = git_revision(self.root)
        path = manager.create(record.round_id, "workspace", base_ref=base_revision)
        self.state.set_workspace_path(record.round_id, str(path))
        self._event(
            record.round_id,
            "workspace_created",
            record.current_stage,
            {"path": str(path), "base_revision": base_revision},
        )
        return path

    def _context_for(self, profile: TaskProfile, stage_ref: str, requested_tier: int, triggers=()):
        tokens = self.config.stage_budgets.get(stage_ref, self.config.context.base_budget_tokens)
        tokens = max(1, min(tokens, self.config.context.max_budget_tokens))
        objective = ContextItem(
            key="objective",
            content=profile.objective,
            source="task-profile",
            tokens=estimate_tokens(profile.objective),
            query_relevance=1.0,
            stage_relevance=1.0,
            authority=1.0,
            required=True,
            tier=0,
        )
        return self.context.resolve(
            query=profile.objective,
            stage_ref=stage_ref,
            budget=ContextBudget(tokens, self.config.context.max_tier),
            base_items=(objective,),
            triggers=triggers,
            requested_tier=min(requested_tier, self.config.context.max_tier),
        )

    def _select_model(self, round_id, profile, stage_ref, input_tokens, settings):
        if self.dry_run:
            return "dry-run", {"provider": "dry-run", "model": "dry-run", "utility": 1.0}
        candidates = [
            ModelCandidate(
                item.name,
                item.provider,
                item.family,
                item.max_context,
                item.input_cost_per_million,
                item.output_cost_per_million,
                item.latency_ms,
                item.reliability,
                item.quality_prior,
                item.capabilities,
                item.privacy_class,
            )
            for item in self.config.models
            if item.provider == self.config.agent.provider
        ]
        if not candidates:
            raise ValueError(f"no models configured for provider {self.config.agent.provider}")
        task_class = (
            "code" if stage_ref in {"build.writer", "build.tester", "quick.execute"} else "text"
        )
        capabilities = set(profile.required_capabilities)
        capabilities.add(task_class)
        writer_model = self._writer_model(round_id) if stage_ref == "build.tester" else None
        request = ModelRequest(
            stage_ref,
            task_class,
            input_tokens,
            settings.max_output_tokens,
            profile.stakes,
            profile.latency_tolerance_ms,
            profile.budget_usd,
            frozenset(capabilities),
            max_privacy_class=0,
            writer_model=writer_model,
        )
        decision = ModelRouter(
            candidates,
            self.performance,
            HeuristicCorrelation(candidates),
        ).choose(request)
        return decision.model.name, {
            "provider": decision.model.provider,
            "model": decision.model.name,
            "utility": decision.utility,
            "estimated_cost_usd": decision.estimated_cost_usd,
            "explanation": dict(decision.explanation),
        }

    def _writer_model(self, round_id: str) -> str | None:
        for event in reversed(self.state.list_events(round_id)):
            if event.stage_ref in {"build.writer", "quick.execute"} and (
                event.kind == "model_selected"
            ):
                return str(event.payload.get("model"))
        return None

    def _model_feedback(self, model_name: str | None, stage_ref: str, success: bool) -> None:
        if self.dry_run or not model_name:
            return
        config = next((item for item in self.config.models if item.name == model_name), None)
        if config:
            task_class = (
                "code" if stage_ref in {"build.writer", "build.tester", "quick.execute"} else "text"
            )
            self.performance.update(
                model_name, stage_ref, task_class, success, config.quality_prior
            )

    def _profile(self, record: RoundRecord) -> TaskProfile:
        data = dict(record.profile or {})
        data.setdefault("objective", record.objective)
        data["intent"] = TaskIntent(data.get("intent", "auto"))
        data["required_capabilities"] = frozenset(data.get("required_capabilities", ()))
        return TaskProfile(**data)

    def _gate_is_approved(self, round_id: str, stage_ref: str) -> bool:
        """True only if the gate was approved on the *current* visit.

        A stage can be re-entered (a later stage ``return_to``s past it, or the round is
        retried after edits). Scoping the approval to events after the most recent
        ``gate_waiting`` for this stage means a one-time approval can't silently authorize a
        second, changed pass through the same gate.
        """
        last_waiting_id = -1
        last_approved_id = -1
        for event in self.state.list_events(round_id):
            if event.stage_ref != stage_ref:
                continue
            if event.kind == "gate_waiting":
                last_waiting_id = event.id
            elif event.kind == "gate_approved":
                last_approved_id = event.id
        return last_approved_id > last_waiting_id and last_approved_id != -1

    def _resource_key(self, stage_ref: str, workspace: Path, mutates: bool) -> str:
        access = "write" if mutates else "read"
        return f"workspace:{workspace}:{access}:{stage_ref}"

    def _event(
        self,
        round_id: str,
        kind: str,
        stage_ref: str | None,
        payload: Mapping[str, Any],
    ) -> EventRecord:
        safe_payload = json.loads(json.dumps(dict(payload), default=str))
        event = self.state.record_event(round_id, kind, stage_ref, safe_payload)
        self.audit.emit(AuditEvent(kind, round_id, stage_ref, safe_payload))
        return event

    def _write_current(self, round_id: str) -> None:
        path = self.root / "2_Working_State/CURRENT"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(round_id + "\n", encoding="utf-8")

    def _clear_current_if(self, round_id: str) -> None:
        path = self.root / "2_Working_State/CURRENT"
        if path.exists() and path.read_text(encoding="utf-8").strip() == round_id:
            path.write_text("NONE\n", encoding="utf-8")

    @staticmethod
    def round_payload(record: RoundRecord) -> dict[str, Any]:
        payload = asdict(record)
        payload["route"] = list(record.route)
        payload["stages"] = list(record.stages)
        payload["current_stage"] = record.current_stage
        return payload
