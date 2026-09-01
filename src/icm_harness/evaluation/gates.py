from dataclasses import dataclass
from pathlib import Path

from icm_harness.kernel.contracts import StageSpec
from icm_harness.kernel.errors import ContractViolation


@dataclass(frozen=True, slots=True)
class GateReport:
    passed: bool
    missing_outputs: tuple[str, ...]


def validate_stage_outputs(stage: StageSpec, output_dir: str | Path) -> GateReport:
    root = Path(output_dir)
    missing = tuple(name for name in stage.required_outputs if not (root / name).exists())
    return GateReport(not missing, missing)


def require_stage_outputs(stage: StageSpec, output_dir: str | Path) -> None:
    report = validate_stage_outputs(stage, output_dir)
    if not report.passed:
        raise ContractViolation(
            f"{stage.ref} missing required outputs: {', '.join(report.missing_outputs)}"
        )
