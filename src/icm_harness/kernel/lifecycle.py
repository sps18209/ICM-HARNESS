import uuid
from collections.abc import Callable
from dataclasses import dataclass

from icm_harness.kernel.contracts import (
    ModeRoute,
    StageResult,
    StageSpec,
    StageStatus,
    TaskProfile,
)
from icm_harness.kernel.errors import ContractViolation, InvalidTransition
from icm_harness.kernel.state import RoundRecord, SQLiteStateStore


@dataclass
class RoundController:
    """Round state machine.

    The stage catalog lives in the ``modes`` module (a feature layer). ``kernel``
    is the primitive layer and must not depend on a feature, so the two lookups
    it needs are injected by the wiring layer rather than imported here. This
    keeps the internal dependency graph a DAG (see
    ``scripts/validate_architecture.py``).
    """

    state: SQLiteStateStore
    get_stage: Callable[[str], StageSpec]
    stage_refs_for_route: Callable[[ModeRoute], tuple[str, ...]]

    def create(self, profile: TaskProfile, route: ModeRoute) -> RoundRecord:
        round_id = f"r-{uuid.uuid4().hex[:12]}"
        profile_payload = {
            "objective": profile.objective,
            "intent": profile.intent.value,
            "specification_clarity": profile.specification_clarity,
            "epistemic_uncertainty": profile.epistemic_uncertainty,
            "stakes": profile.stakes,
            "reversibility": profile.reversibility,
            "production_change_required": profile.production_change_required,
            "code_intensity": profile.code_intensity,
            "research_intensity": profile.research_intensity,
            "tool_intensity": profile.tool_intensity,
            "privacy_restricted": profile.privacy_restricted,
            "latency_tolerance_ms": profile.latency_tolerance_ms,
            "budget_usd": profile.budget_usd,
            "required_capabilities": sorted(profile.required_capabilities),
        }
        return self.state.create_round(
            round_id,
            profile.objective,
            [m.value for m in route.modes],
            self.stage_refs_for_route(route),
            profile=profile_payload,
            route_reason=route.reason,
        )

    def complete_stage(self, round_id: str, result: StageResult) -> RoundRecord:
        current = self.state.get_round(round_id)
        if current.current_stage is None:
            raise InvalidTransition("round already closed")
        self.state.record_event(
            round_id,
            "stage_result",
            current.current_stage,
            {
                "status": result.status.value,
                "summary": result.summary,
                "return_to": result.return_to,
                "triggers": list(result.trigger_codes),
            },
        )
        stage = self.get_stage(current.current_stage)
        if result.return_to and result.return_to not in stage.permitted_return_stages:
            raise ContractViolation(f"{stage.ref} may not return control to {result.return_to}")
        if result.status is StageStatus.PASS:
            if result.return_to:
                raise ContractViolation("PASS result may not set return_to")
            return self.state.advance(round_id, current.version)
        if result.return_to:
            return self.state.jump_to(round_id, result.return_to, current.version)
        return current
