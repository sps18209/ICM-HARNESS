"""test_intake_eval.py — the intake-accuracy eval's scoring logic, hermetically.

The live eval (`icm intake-eval`) makes a real model call per case, so it can't
run in CI. Its scoring, though, is pure and dependency-injected: a fake proposer
returns canned `IntakeResult`s, the REAL router scores them, and we assert the
report. This proves run_eval wires propose -> recommended answers -> finalize ->
route and tallies correctly — including that a case's recommended answer (not
just the draft) reaches the routed profile.
"""
from __future__ import annotations

from icm_harness import intake
from icm_harness.intake.contracts import IntakeChoice, IntakeQuestion, IntakeResult
from icm_harness.kernel.contracts import TaskIntent
from icm_harness.routing import ModeRouter


def _route(profile) -> str:
    return str(ModeRouter().route(profile).modes[0])


def _result(intent=None, questions=()):
    draft = {"intent": TaskIntent(intent)} if intent else {}
    return IntakeResult(restated_objective=f"r:{intent}", profile_draft=draft, questions=questions)


# A question whose RECOMMENDED choice (index 1) pins intent=review — so routing
# the labelled case correctly depends on finalize folding the recommended answer
# in, not merely on the draft.
_REVIEW_Q = IntakeQuestion(
    id="kind",
    prompt="Reviewing or making?",
    choices=(
        IntakeChoice(label="Making something", sets={}),
        IntakeChoice(label="Reviewing", sets={"intent": TaskIntent.REVIEW}),
    ),
    recommended=1,
)

_PROPOSALS = {
    "quick one": _result("quick"),
    "decide one": _result("decide"),
    "answer-driven review": _result(None, (_REVIEW_Q,)),
}


def _propose(objective: str):
    return _PROPOSALS[objective]


def test_run_eval_scores_all_correct():
    cases = [
        intake.EvalCase("quick one", "quick"),
        intake.EvalCase("decide one", "decision"),
        intake.EvalCase("answer-driven review", "review"),
    ]
    report = intake.run_eval(cases, route=_route, propose=_propose)
    assert report.total == 3
    assert report.passed == 3
    assert report.accuracy == 1.0
    # The recommended answer, not the (empty) draft, is what routed it to review.
    by_request = {r.request: r for r in report.results}
    assert by_request["answer-driven review"].actual_mode == "review"


def test_run_eval_counts_a_mislabel_as_a_miss():
    cases = [
        intake.EvalCase("quick one", "review"),   # wrong label on purpose
        intake.EvalCase("decide one", "decision"),
    ]
    report = intake.run_eval(cases, route=_route, propose=_propose)
    assert report.passed == 1
    assert report.total == 2
    assert report.accuracy == 0.5
    miss = next(r for r in report.results if r.request == "quick one")
    assert miss.ok is False
    assert miss.actual_mode == "quick"


def test_run_eval_records_a_failing_case_without_aborting():
    def _boom(objective: str):
        if objective == "explodes":
            raise RuntimeError("model down")
        return _PROPOSALS[objective]

    cases = [
        intake.EvalCase("explodes", "quick"),
        intake.EvalCase("decide one", "decision"),
    ]
    report = intake.run_eval(cases, route=_route, propose=_boom)
    assert report.total == 2
    assert report.passed == 1  # the second case still ran and passed
    bad = next(r for r in report.results if r.request == "explodes")
    assert bad.ok is False
    assert bad.actual_mode.startswith("error:")


def test_default_cases_are_well_formed():
    assert intake.DEFAULT_CASES
    valid = {"discovery", "build", "decision", "review", "quick"}
    for case in intake.DEFAULT_CASES:
        assert case.request.strip()
        assert case.expected_mode in valid


def test_empty_report_has_zero_accuracy():
    report = intake.run_eval([], route=_route, propose=_propose)
    assert report.total == 0
    assert report.accuracy == 0.0
