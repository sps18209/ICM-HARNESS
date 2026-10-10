"""A small labelled set that measures intake ROUTING ACCURACY end to end.

This is the Phase-3 "live eval" the design spec names: a handful of real
plain-English requests, each labelled with the mode a correct intake should
route it to. Each case is run through the real `propose()` (one model call),
auto-answered with the model's own recommended choices (the `-y` path), folded
deterministically into a `TaskProfile` by `finalize()`, and routed — then the
primary mode is compared to the label.

It measures the model's judgement, so it is NOT wired into CI (it needs a live
`claude` and real inference is non-deterministic). The scoring logic, though, is
pure and dependency-injected, so `test_intake_eval.py` exercises it hermetically
with a fake agent. `icm intake-eval` runs it against the configured agent.

The router is injected rather than imported, so this module adds no
`intake -> routing` dependency edge: the CLI (which already knows the router)
wires it in.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from icm_harness.intake.agent import finalize
from icm_harness.intake.agent import propose as _propose
from icm_harness.intake.contracts import IntakeResult
from icm_harness.kernel.contracts import TaskProfile

# A primary-mode router: TaskProfile -> the mode name the round would run as.
# `Mode` is a StrEnum, so returning a Mode compares equal to its label string.
RouteFn = Callable[[TaskProfile], str]
# A proposer: objective -> IntakeResult (the one model call). Injectable so the
# eval can run against the real `claude` CLI or a fake in tests.
ProposeFn = Callable[[str], IntakeResult]


@dataclass(frozen=True)
class EvalCase:
    """One labelled request: plain English in, expected primary mode out."""

    request: str
    expected_mode: str
    note: str = ""


@dataclass(frozen=True)
class EvalCaseResult:
    request: str
    expected_mode: str
    actual_mode: str
    ok: bool
    restated_objective: str = ""


@dataclass(frozen=True)
class EvalReport:
    results: tuple[EvalCaseResult, ...] = field(default_factory=tuple)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def accuracy(self) -> float:
        return self.passed / self.total if self.results else 0.0


# The labelled set. Guards the four worked examples in the design spec (§4) with
# real inference, plus a few neighbours that pull on each signal. Keep it small
# and unambiguous — every case is one a correct router must agree on.
DEFAULT_CASES: tuple[EvalCase, ...] = (
    EvalCase("fix the typo in the footer of the homepage", "quick",
             "clear, tiny, reversible -> quick"),
    EvalCase("bump the copyright year in the LICENSE file", "quick",
             "trivial clear edit -> quick"),
    EvalCase("build an app to track my runs — I'm not sure how it should work yet",
             "discovery", "low clarity, build intent -> discovery first"),
    EvalCase("design and build a notifications system for our product; "
             "the approach is open", "discovery",
             "open-ended build -> discovery first"),
    EvalCase("should we use Postgres or SQLite for this service?", "decision",
             "decide intent -> decision"),
    EvalCase("help me choose between REST and gRPC for the new API", "decision",
             "decide intent -> decision"),
    EvalCase("review this pull request and tell me what to fix", "review",
             "review intent -> review"),
    EvalCase("look over my authentication code for problems", "review",
             "review intent -> review"),
)


def run_eval(
    cases: Sequence[EvalCase] = DEFAULT_CASES,
    *,
    route: RouteFn,
    propose: ProposeFn | None = None,
) -> EvalReport:
    """Score each case end to end and return a report.

    `route` is required and injected (TaskProfile -> primary mode name), so this
    module never imports the router. `propose` defaults to the real one-model-call
    `propose()`; tests pass a fake. A case that raises is recorded as a failure
    with the error as its actual mode, never aborting the run — one off request
    must not sink the whole score.
    """
    proposer: ProposeFn = propose if propose is not None else _propose
    results: list[EvalCaseResult] = []
    for case in cases:
        try:
            result = proposer(case.request)
            answers = [q.recommended for q in result.questions]
            profile = finalize(case.request, result, answers)
            actual = str(route(profile))
            restated = result.restated_objective
        except Exception as exc:  # noqa: BLE001 — a bad case fails, never aborts
            actual = f"error: {type(exc).__name__}"
            restated = ""
        results.append(
            EvalCaseResult(
                request=case.request,
                expected_mode=case.expected_mode,
                actual_mode=actual,
                ok=(actual == case.expected_mode),
                restated_objective=restated,
            )
        )
    return EvalReport(results=tuple(results))
