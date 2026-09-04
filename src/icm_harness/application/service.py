from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from icm_harness.agents import StageAgent, StageCancelled, StageInvocation, make_stage_agent
from icm_harness.application.artifacts import ArtifactStore
from icm_harness.config import HarnessConfig, load_config
from icm_harness.context import (
    ContextBudget,
    ContextEngine,
    FilesystemWikiProvider,
    estimate_tokens,
)
from icm_harness.evaluation import require_stage_outputs
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
from icm_harness.kernel.state import ArtifactRecord, EventRecord, RoundRecord, SQLiteStateStore
from icm_harness.modes import get_stage, stage_refs_for_route
from icm_harness.observability import AuditEvent, JsonlAuditSink
from icm_harness.policies import AuthorizationPolicy, SituationalSettingsPolicy
from icm_harness.routing import (
    BayesianPerformanceStore,
    HeuristicCorrelation,
    ModelRouter,
    ModeRouter,
)
from icm_harness.workspace import GitWorktreeManager

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
    ):
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
        self.dry_run = dry_run
        self.agent = agent or make_stage_agent(self.config.agent, dry_run=dry_run)

    def create_round(self, profile: TaskProfile) -> RoundRecord:
        route = ModeRouter().route(profile)
        record = self.controller.create(profile, route)
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

    def promote_round(self, round_id: str) -> RoundRecord:
        record = self.state.get_round(round_id)
        if record.status != "closed":
            raise ValueError(f"round {round_id} must be closed before promotion")
        if not record.workspace_path:
            raise ValueError(f"round {round_id} has no isolated workspace to promote")
        if any(event.kind == "round_promoted" for event in self.state.list_events(round_id)):
            raise ValueError(f"round {round_id} was already promoted")
        commit = GitWorktreeManager(self.root, self.config.workspace.worktree_root).promote(
            record.workspace_path, message=f"ICM round {round_id}: {record.objective}"
        )
        self._event(round_id, "round_promoted", None, {"commit": commit})
        return self.state.get_round(round_id)

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

            result = await self._run_stage(record, owner)
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
        settings = self.settings_policy.settings(stage.ref, stakes=profile.stakes)
        workspace = self._workspace_for(record, stage.mutates_workspace)
        artifact_dir = self.artifacts.stage_dir(record.round_id, stage.ref)
        context = self._context_for(profile, stage.ref, settings.context_tier)
        model_name, model_payload = self._select_model(
            record.round_id, profile, stage.ref, context.used_tokens, settings
        )
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
        path = manager.create(record.round_id, "workspace")
        self.state.set_workspace_path(record.round_id, str(path))
        self._event(record.round_id, "workspace_created", record.current_stage, {"path": str(path)})
        return path

    def _context_for(self, profile: TaskProfile, stage_ref: str, requested_tier: int):
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
            if event.stage_ref == "build.writer" and event.kind == "model_selected":
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
        return any(
            event.kind == "gate_approved" and event.stage_ref == stage_ref
            for event in self.state.list_events(round_id)
        )

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
