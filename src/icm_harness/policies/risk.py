from dataclasses import dataclass

from icm_harness.kernel.contracts import TaskProfile


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    score: float
    level: str
    requires_independent_review: bool
    requires_human_gate: bool


def assess_risk(profile: TaskProfile) -> RiskAssessment:
    score = min(
        1.0,
        0.55 * profile.stakes
        + 0.25 * (1 - profile.reversibility)
        + 0.20 * profile.epistemic_uncertainty,
    )
    level = "low" if score < 0.35 else "medium" if score < 0.7 else "high"
    return RiskAssessment(score, level, score >= 0.55, score >= 0.8)
