from icm_harness.kernel.contracts import Mode, TaskProfile
from icm_harness.routing.mode_router import ModeRouter


def test_uncertain_build_routes_discovery_then_build():
    task = TaskProfile(
        "new architecture",
        production_change_required=True,
        specification_clarity=0.5,
        epistemic_uncertainty=0.8,
        stakes=0.7,
    )
    assert ModeRouter().route(task).modes == (Mode.DISCOVERY, Mode.BUILD)


def test_clear_low_risk_reversible_change_can_be_quick():
    task = TaskProfile(
        "rename",
        production_change_required=True,
        specification_clarity=0.95,
        epistemic_uncertainty=0.05,
        stakes=0.1,
        reversibility=0.95,
    )
    assert ModeRouter().route(task).modes == (Mode.QUICK,)
