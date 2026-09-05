from __future__ import annotations

import json

import pytest

from icm_harness.intake import finalize, propose
from icm_harness.intake.agent import _clean_profile_fields, _default_agent_fn  # noqa: F401
from icm_harness.kernel.contracts import Mode, TaskIntent
from icm_harness.routing.mode_router import ModeRouter


# A fake intake agent: returns a canned envelope-free JSON string (propose()
# runs extract_json + json.loads on it), so the real parse path is exercised
# without a live `claude` CLI.
def _fake_agent(payload: dict):
    def agent_fn(prompt: str) -> str:
        return json.dumps(payload)

    return agent_fn


def _fenced_agent(payload: dict):
    def agent_fn(prompt: str) -> str:
        return "```json\n" + json.dumps(payload) + "\n```"

    return agent_fn


BUILD_PAYLOAD = {
    "restated_objective": "Build a personal running-log app.",
    "profile_draft": {
        "intent": "build",
        "specification_clarity": 0.35,
        "epistemic_uncertainty": 0.6,
        "stakes": 0.4,
        "reversibility": 0.8,
        "production_change_required": False,
        "code_intensity": 0.7,
    },
    "questions": [
        {
            "id": "surface",
            "prompt": "Who is this for?",
            "recommended": 0,
            "choices": [
                {"label": "Just me", "sets": {"stakes": 0.2, "production_change_required": False}},
                {"label": "Real users",
                 "sets": {"stakes": 0.7, "production_change_required": True}},
            ],
        },
        {
            "id": "clarity",
            "prompt": "Do you know how it should work?",
            "recommended": 1,
            "choices": [
                {"label": "Yes",
                 "sets": {"specification_clarity": 0.9, "epistemic_uncertainty": 0.1}},
                {"label": "Partly",
                 "sets": {"specification_clarity": 0.4, "epistemic_uncertainty": 0.6}},
            ],
        },
    ],
}


# --- parsing -----------------------------------------------------------------


def test_propose_parses_draft_and_questions():
    result = propose("build a run tracker", agent_fn=_fake_agent(BUILD_PAYLOAD))
    assert result.restated_objective == "Build a personal running-log app."
    assert result.profile_draft["intent"] is TaskIntent.BUILD
    assert len(result.questions) == 2
    assert result.questions[0].choices[1].sets["production_change_required"] is True
    assert result.questions[1].recommended == 1


def test_propose_salvages_a_fenced_result():
    result = propose("x", agent_fn=_fenced_agent(BUILD_PAYLOAD))
    assert result.profile_draft["intent"] is TaskIntent.BUILD


def test_propose_caps_questions_at_four():
    payload = dict(BUILD_PAYLOAD)
    payload["questions"] = [
        {"id": f"q{i}", "prompt": "?", "choices": [{"label": "a"}]} for i in range(9)
    ]
    result = propose("x", agent_fn=_fake_agent(payload))
    assert len(result.questions) <= 4


def test_clean_profile_fields_clamps_and_drops_unknown():
    cleaned = _clean_profile_fields(
        {"stakes": 5.0, "reversibility": -1, "intent": "nonsense", "bogus": 1}
    )
    assert cleaned["stakes"] == 1.0
    assert cleaned["reversibility"] == 0.0
    assert "intent" not in cleaned  # invalid label dropped, not guessed
    assert "bogus" not in cleaned


def test_off_contract_payload_raises():
    def agent_fn(prompt: str) -> str:
        return "I could not follow the schema."

    # extract_json returns the prose unchanged, json.loads then raises
    # (JSONDecodeError is a ValueError subclass) — intake fails, never guesses.
    with pytest.raises(ValueError):
        propose("x", agent_fn=agent_fn)


# --- finalize: answers → profile --------------------------------------------


def test_finalize_applies_chosen_answers_over_draft():
    result = propose("build a run tracker", agent_fn=_fake_agent(BUILD_PAYLOAD))
    # choose "Real users" (index 1) and "Partly" (index 1)
    profile = finalize("build a run tracker", result, [1, 1])
    assert profile.objective == "build a run tracker"  # original wording kept
    assert profile.production_change_required is True   # from the chosen answer
    assert profile.stakes == 0.7
    assert profile.specification_clarity == 0.4
    assert profile.intent is TaskIntent.BUILD


def test_finalize_uses_draft_when_no_answers_change_a_field():
    result = propose("x", agent_fn=_fake_agent(BUILD_PAYLOAD))
    profile = finalize("x", result, [0, 0])  # "Just me", "Yes"
    assert profile.stakes == 0.2
    assert profile.specification_clarity == 0.9


# --- golden: plain request → routed mode ------------------------------------
#
# The whole point of intake is that a bare request routes correctly. These run
# the fake-agent payload through finalize + the REAL deterministic router.


def _route(payload: dict, answers: list[int]) -> Mode:
    result = propose(payload["restated_objective"], agent_fn=_fake_agent(payload))
    profile = finalize(payload["restated_objective"], result, answers)
    return ModeRouter().route(profile).modes[0]


def test_golden_uncertain_build_routes_to_discovery():
    # "Real users" + "Partly sure" → low clarity, high uncertainty → discovery
    assert _route(BUILD_PAYLOAD, [1, 1]) is Mode.DISCOVERY


def test_golden_clear_quick_task_routes_to_quick():
    payload = {
        "restated_objective": "Fix the typo in the footer.",
        "profile_draft": {
            "intent": "quick",
            "specification_clarity": 0.95,
            "epistemic_uncertainty": 0.05,
            "stakes": 0.1,
            "reversibility": 0.95,
        },
        "questions": [],
    }
    assert _route(payload, []) is Mode.QUICK


def test_golden_decision_request_routes_to_decision():
    payload = {
        "restated_objective": "Decide Postgres vs SQLite.",
        "profile_draft": {"intent": "decide"},
        "questions": [],
    }
    assert _route(payload, []) is Mode.DECISION


def test_golden_review_request_routes_to_review():
    payload = {
        "restated_objective": "Review this pull request.",
        "profile_draft": {"intent": "review"},
        "questions": [],
    }
    assert _route(payload, []) is Mode.REVIEW
