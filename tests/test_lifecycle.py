from icm_harness.kernel.contracts import Mode, ModeRoute, StageResult, StageStatus, TaskProfile
from icm_harness.kernel.lifecycle import RoundController
from icm_harness.kernel.state import SQLiteStateStore


def test_failure_does_not_advance(tmp_path):
    controller = RoundController(SQLiteStateStore(tmp_path / "s.db"))
    rec = controller.create(TaskProfile("x"), ModeRoute((Mode.BUILD,), "test"))
    rec = controller.complete_stage(rec.round_id, StageResult(StageStatus.FAIL, "bad"))
    assert rec.current_stage == "build.planner"


def test_plan_failure_can_return_tester_to_planner(tmp_path):
    controller = RoundController(SQLiteStateStore(tmp_path / "s.db"))
    rec = controller.create(TaskProfile("x"), ModeRoute((Mode.BUILD,), "test"))
    rec = controller.complete_stage(rec.round_id, StageResult(StageStatus.PASS, "planned"))
    rec = controller.complete_stage(rec.round_id, StageResult(StageStatus.PASS, "written"))
    assert rec.current_stage == "build.tester"
    rec = controller.complete_stage(
        rec.round_id,
        StageResult(StageStatus.FAIL, "plan defect", return_to="build.planner"),
    )
    assert rec.current_stage == "build.planner"
