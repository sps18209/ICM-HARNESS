from icm_harness.evaluation.gates import validate_stage_outputs
from icm_harness.modes.catalog import get_stage


def test_planner_gate_requires_both_artifacts(tmp_path):
    stage = get_stage("build.planner")
    (tmp_path / "execution-plan.md").write_text("x")
    report = validate_stage_outputs(stage, tmp_path)
    assert not report.passed
    assert report.missing_outputs == ("context-manifest.json",)
