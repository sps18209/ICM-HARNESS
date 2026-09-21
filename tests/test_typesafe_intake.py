from __future__ import annotations

from types import SimpleNamespace

import pytest

from icm_harness.config import load_config
from icm_harness.intake import finalize
from icm_harness.integrations.typesafe import (
    SystemOneIntakeClient,
    build_intake_result,
    build_questions,
    propose_intake,
    resolve_api_key,
)
from icm_harness.kernel.contracts import TaskIntent
from icm_harness.kernel.errors import IntegrationUnavailable


@pytest.fixture(autouse=True)
def _isolated_global_env(monkeypatch, tmp_path_factory):
    """Point the per-user key file somewhere empty so a developer's real
    ~/.icm/env can never change what these tests observe."""
    from icm_harness.integrations.typesafe import adapter

    monkeypatch.setattr(
        adapter, "GLOBAL_ENV_PATH", tmp_path_factory.mktemp("icm-home") / "env"
    )


def _choice(choice: str, confidence: float):
    return SimpleNamespace(choice=choice, confidence=confidence)


def _score(score: float, confidence: float):
    return SimpleNamespace(score=score, confidence=confidence)


def _noul(noul: float):
    return SimpleNamespace(noul=noul)


def _confident_answers() -> dict:
    return {
        "intent": _choice("build", 0.9),
        "specification_clarity": _score(1.8, 0.9),
        "epistemic_uncertainty": _score(0.4, 0.9),
        "stakes": _score(1.0, 0.9),
        "reversibility": _score(2.0, 0.9),
        "code_intensity": _score(1.6, 0.9),
        "research_intensity": _score(0.2, 0.9),
        "tool_intensity": _score(0.6, 0.9),
        "production_change_required": _noul(0.95),
        "privacy_restricted": _noul(0.02),
    }


class FakeClient:
    def __init__(self, answers: dict):
        self.answers = answers
        self.calls: list[dict] = []

    def system_one(self, *, state: str, questions: dict):
        self.calls.append({"state": state, "questions": questions})
        return self.answers


# --- question construction ---------------------------------------------------


def test_build_questions_covers_every_profile_field():
    questions = build_questions()
    assert questions["intent"]["type"] == "choice"
    assert "auto" not in questions["intent"]["criteria"]  # auto is the router's default
    score_fields = [n for n, q in questions.items() if q["type"] == "score"]
    noul_fields = [n for n, q in questions.items() if q["type"] == "noul"]
    assert len(score_fields) == 7
    assert set(noul_fields) == {"production_change_required", "privacy_restricted"}


# --- answer folding ----------------------------------------------------------


def test_confident_answers_yield_full_draft_and_no_questions():
    result = build_intake_result(_confident_answers())
    assert result.restated_objective == ""  # Jev writes no prose
    assert result.questions == ()
    assert result.profile_draft["intent"] is TaskIntent.BUILD
    assert result.profile_draft["specification_clarity"] == pytest.approx(0.9)
    assert result.profile_draft["reversibility"] == 1.0
    assert result.profile_draft["production_change_required"] is True
    assert result.profile_draft["privacy_restricted"] is False


def test_scores_are_normalized_and_clamped():
    answers = _confident_answers()
    answers["stakes"] = _score(2.6, 0.9)  # out-of-range score clamps to 1.0
    result = build_intake_result(answers)
    assert result.profile_draft["stakes"] == 1.0


def test_low_confidence_intent_is_left_to_the_router():
    answers = _confident_answers()
    answers["intent"] = _choice("build", 0.3)
    result = build_intake_result(answers)
    assert "intent" not in result.profile_draft


def test_unknown_intent_choice_is_dropped():
    answers = _confident_answers()
    answers["intent"] = _choice("refactor-the-universe", 0.99)
    result = build_intake_result(answers)
    assert "intent" not in result.profile_draft


def test_low_confidence_fields_earn_questions_least_certain_first():
    answers = _confident_answers()
    answers["stakes"] = _score(1.0, 0.4)
    answers["specification_clarity"] = _score(1.0, 0.6)
    answers["production_change_required"] = _noul(0.55)  # certainty 0.1: least sure
    result = build_intake_result(answers)
    assert [q.id for q in result.questions] == [
        "production_change_required",
        "stakes",
        "specification_clarity",
    ]


def test_question_count_is_capped():
    answers = _confident_answers()
    for field in (
        "specification_clarity",
        "epistemic_uncertainty",
        "stakes",
        "reversibility",
        "code_intensity",
        "research_intensity",
    ):
        answers[field] = _score(1.0, 0.2)
    result = build_intake_result(answers)
    assert len(result.questions) == 4


def test_bool_question_not_sure_pins_nothing_and_finalize_folds_choices():
    answers = _confident_answers()
    answers["production_change_required"] = _noul(0.52)
    answers["stakes"] = _score(1.0, 0.3)
    result = build_intake_result(answers)
    by_id = {q.id: q for q in result.questions}

    bool_q = by_id["production_change_required"]
    assert bool_q.recommended == 0  # drafted True at p=0.52
    assert bool_q.choices[2].label == "Not sure" and bool_q.choices[2].sets == {}

    # Answer "No" for production change and "Seriously bad" for stakes; the
    # deterministic finalize() must fold both onto the draft.
    picks = []
    for question in result.questions:
        if question.id == "production_change_required":
            picks.append(1)
        elif question.id == "stakes":
            picks.append(2)
        else:
            picks.append(question.recommended)
    profile = finalize("ship the widget", result, picks)
    assert profile.objective == "ship the widget"
    assert profile.production_change_required is False
    assert profile.stakes == pytest.approx(0.85)


def test_recommended_float_choice_tracks_the_drafted_value():
    answers = _confident_answers()
    answers["stakes"] = _score(1.9, 0.3)  # drafted 0.95 → "Seriously bad" (0.85)
    result = build_intake_result(answers)
    stakes_q = next(q for q in result.questions if q.id == "stakes")
    assert stakes_q.choices[stakes_q.recommended].sets["stakes"] == pytest.approx(0.85)


# --- propose_intake ----------------------------------------------------------


def test_propose_intake_sends_objective_and_env_facts():
    client = FakeClient(_confident_answers())
    result = propose_intake(
        "add a hello endpoint", env_facts={"is_git_repo": True}, client=client
    )
    assert result.profile_draft["intent"] is TaskIntent.BUILD
    (call,) = client.calls
    assert "add a hello endpoint" in call["state"]
    assert "is_git_repo" in call["state"]
    assert set(call["questions"]) == set(build_questions())


def test_dict_shaped_answers_are_accepted():
    answers = {name: vars(value) for name, value in _confident_answers().items()}
    result = build_intake_result(answers)
    assert result.profile_draft["intent"] is TaskIntent.BUILD


# --- setup guardrails --------------------------------------------------------


def test_default_client_requires_sdk_or_key(monkeypatch, tmp_path):
    # Whether or not typesafe-sdk is installed, a missing TYPESAFE_API_KEY
    # (no env var, no ./.env) must fail closed with a setup hint.
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(IntegrationUnavailable):
        SystemOneIntakeClient()


def test_resolve_api_key_prefers_env_then_dotenv(monkeypatch, tmp_path):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert resolve_api_key(tmp_path) is None

    (tmp_path / ".env").write_text(
        "PORTKEY_API_KEY=other\nTYPESAFE_API_KEY = 'ts_from_file'\n"
    )
    assert resolve_api_key(tmp_path) == "ts_from_file"

    monkeypatch.setenv("TYPESAFE_API_KEY", "ts_from_env")
    assert resolve_api_key(tmp_path) == "ts_from_env"


def test_resolve_api_key_ignores_blank_value(monkeypatch, tmp_path):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    (tmp_path / ".env").write_text("TYPESAFE_API_KEY=\n")  # the template line
    assert resolve_api_key(tmp_path) is None


def test_intake_config_defaults_and_validation(tmp_path):
    config = load_config(tmp_path)
    assert config.intake.profiler == "claude-cli"
    assert config.intake.ask_threshold == pytest.approx(0.75)

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    (harness_dir / "config.toml").write_text('[intake]\nprofiler = "typesafe"\n')
    assert load_config(tmp_path).intake.profiler == "typesafe"

    (harness_dir / "config.toml").write_text('[intake]\nprofiler = "ouija-board"\n')
    with pytest.raises(ValueError):
        load_config(tmp_path)


def test_intake_profiler_env_override(tmp_path):
    config = load_config(tmp_path, environ={"ICM_INTAKE_PROFILER": "typesafe"})
    assert config.intake.profiler == "typesafe"


# --- semantic stage gate (point 2) --------------------------------------------


def test_review_stage_outputs_folds_answers_and_state(monkeypatch):
    client = FakeClient(
        {
            "addresses_objective": _noul(0.9),
            "claims_verified": _noul(0.3),
            "quality": SimpleNamespace(score=1.7, confidence=0.8),
        }
    )
    from icm_harness.integrations.typesafe import review_stage_outputs

    review = review_stage_outputs(
        "ship the widget",
        "build.tester",
        {"test-report.json": '{"passed": true}', "notes.md": "# notes"},
        client=client,
    )
    assert review.addresses_objective == pytest.approx(0.9)
    assert review.claims_verified == pytest.approx(0.3)
    assert review.quality == pytest.approx(0.85)
    assert review.concerns() == ("verification claims may be unsubstantiated",)
    (call,) = client.calls
    assert "ship the widget" in call["state"]
    assert "build.tester" in call["state"]
    assert "test-report.json" in call["state"] and "# notes" in call["state"]


def test_review_stage_outputs_clips_oversized_artifacts():
    client = FakeClient(
        {
            "addresses_objective": _noul(0.9),
            "claims_verified": _noul(0.9),
            "quality": SimpleNamespace(score=2.0, confidence=0.9),
        }
    )
    from icm_harness.integrations.typesafe import review_stage_outputs

    review_stage_outputs(
        "objective", "stage", {"big.md": "x" * 100_000}, client=client, per_output_chars=1_000
    )
    (call,) = client.calls
    assert len(call["state"]) < 5_000
    assert "truncated for review" in call["state"]


# --- pre-promotion diff review (point 3) --------------------------------------


def test_review_diff_concerns_and_approval_class():
    from icm_harness.integrations.typesafe import review_diff
    from icm_harness.policies import ApprovalClass

    clean = review_diff(
        "objective",
        "diff --git a/x b/x",
        client=FakeClient(
            {
                "consistent_with_objective": _noul(0.95),
                "touches_production_config": _noul(0.02),
                "removes_tests": _noul(0.01),
                "exposes_secrets": _noul(0.01),
            }
        ),
    )
    assert clean.concerns() == ()
    assert clean.suggested_approval_class() is ApprovalClass.LOCAL_REVERSIBLE

    scary = review_diff(
        "objective",
        "diff --git a/x b/x",
        client=FakeClient(
            {
                "consistent_with_objective": _noul(0.2),
                "touches_production_config": _noul(0.8),
                "removes_tests": _noul(0.1),
                "exposes_secrets": _noul(0.9),
            }
        ),
    )
    assert len(scary.concerns()) == 3
    # secrets outrank the other flags in the ADR-0010 taxonomy
    assert scary.suggested_approval_class() is ApprovalClass.SECURITY_SENSITIVE


def test_review_diff_missing_answers_default_benign():
    from icm_harness.integrations.typesafe import review_diff

    review = review_diff("objective", "diff", client=FakeClient({}))
    assert review.concerns() == ()


def test_api_key_source_order_env_project_then_global(monkeypatch, tmp_path):
    from icm_harness.integrations.typesafe import adapter, api_key_source

    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    global_env = tmp_path / "home-icm-env"
    monkeypatch.setattr(adapter, "GLOBAL_ENV_PATH", global_env)
    project = tmp_path / "project"
    project.mkdir()

    assert api_key_source(project) is None

    global_env.write_text("TYPESAFE_API_KEY=ts_global\n")
    assert api_key_source(project) == ("ts_global", "~/.icm/env")

    (project / ".env").write_text("TYPESAFE_API_KEY=ts_project\n")
    assert api_key_source(project) == ("ts_project", "./.env")

    monkeypatch.setenv("TYPESAFE_API_KEY", "ts_env")
    assert api_key_source(project) == ("ts_env", "environment")
