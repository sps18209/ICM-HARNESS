from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StageSignals:
    gate_passed: bool
    human_revision_fraction: float = 0.0
    repair_iterations: int = 0
    escaped_defect: bool = False
    plan_exception: bool = False


def reward(signals: StageSignals) -> float:
    value = 1.0 if signals.gate_passed else 0.0
    value -= min(0.5, max(0.0, signals.human_revision_fraction) * 0.5)
    value -= min(0.3, signals.repair_iterations * 0.05)
    value -= 0.5 if signals.escaped_defect else 0.0
    value -= 0.25 if signals.plan_exception else 0.0
    return max(0.0, min(1.0, value))
