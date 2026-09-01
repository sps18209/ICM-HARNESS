from dataclasses import dataclass

from icm_harness.policies.risk import RiskAssessment


@dataclass(frozen=True, slots=True)
class StrictCNPolicy:
    enabled: bool = False
    require_competing_hypothesis: bool = True
    require_fmea: bool = True
    require_provenance: bool = True
    require_multiplayer_for_high_risk: bool = True
    max_unresolved_material_unknowns: int = 0

    def required_reviewers(self, risk: RiskAssessment) -> int:
        if not self.enabled:
            return 1
        if risk.level == "high" and self.require_multiplayer_for_high_risk:
            return 3
        return 2 if risk.level == "medium" else 1
