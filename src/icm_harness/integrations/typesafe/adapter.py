"""Intake profiler adapter (TypeSafe Jev / System One).

Maps the intake profile onto one System One call — `intent` as a choice,
the 0–1 float signals as scores, the booleans as nouls — and folds the
calibrated answers into an :class:`IntakeResult`. Per-field confidence
decides which clarifying questions to ask: only fields Jev is unsure about
get one, from a fixed plain-English template, so the guided conversation
is a measurement rather than a guess. Jev generates no text, so the
restated objective is left empty and the user's own wording stands.

Question construction and answer folding are pure and testable; the
network call goes through ``typesafe-sdk`` and raises
:class:`IntegrationUnavailable` when it is not installed or no
``TYPESAFE_API_KEY`` is set.

This adapter sends the objective text (and shallow env facts) to an
external API. It is opt-in via ``[intake] profiler = "typesafe"`` and must
not be wired in for privacy-restricted work.
"""

from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Mapping
from typing import Any

from icm_harness.intake import IntakeChoice, IntakeQuestion, IntakeResult
from icm_harness.kernel.contracts import TaskIntent

MAX_QUESTIONS = 4
ASK_THRESHOLD = 0.75  # certainty below this earns the field a clarifying question

_INTENT_CRITERIA = {
    TaskIntent.BUILD.value: "Implement or change code, features, or systems",
    TaskIntent.INVESTIGATE.value: "Research, explore, or figure something out",
    TaskIntent.DECIDE.value: "Weigh options and make a decision",
    TaskIntent.REVIEW.value: "Audit or review existing work",
    TaskIntent.QUICK.value: "A small, clear, low-risk task",
}

# Each score uses a 3-point rubric; the returned score (0..2) normalizes to 0..1.
_SCORE_FIELDS: dict[str, tuple[str, list[str]]] = {
    "specification_clarity": (
        "How clearly the request already specifies what is wanted",
        ["Vague or open-ended", "Partly specified", "Precisely specified"],
    ),
    "epistemic_uncertainty": (
        "How much is genuinely unknown or needs figuring out before the work can start",
        ["Everything needed is already known", "Some open questions", "Mostly unknown territory"],
    ),
    "stakes": (
        "How much damage a mistake in this work could do",
        ["Harmless if wrong", "Annoying but recoverable", "Serious damage"],
    ),
    "reversibility": (
        "How easily a wrong result could be undone (higher = easier)",
        ["Hard or impossible to undo", "Undoable with effort", "Trivially undone"],
    ),
    "code_intensity": (
        "How much of the work is writing or changing code",
        ["None", "Some", "Most of it"],
    ),
    "research_intensity": (
        "How much of the work is research, reading, or investigation",
        ["None", "Some", "Most of it"],
    ),
    "tool_intensity": (
        "How much of the work is running tools, commands, or external services",
        ["None", "Some", "Most of it"],
    ),
}

_NOUL_FIELDS = {
    "production_change_required": "The work would touch real, live, or shared systems",
    "privacy_restricted": "The request involves private or sensitive data",
}

# Plain-English clarifying question per field, asked only when Jev's answer
# for that field is low-confidence. Float choices pin a value via `sets`;
# "Not sure" pins nothing, leaving the drafted value in place.
_FLOAT_QUESTIONS: dict[str, tuple[str, tuple[tuple[str, float], ...]]] = {
    "specification_clarity": (
        "How settled is what you want?",
        (("Still figuring it out", 0.2), ("Roughly clear", 0.5), ("Exactly specified", 0.9)),
    ),
    "epistemic_uncertainty": (
        "How much needs figuring out before the work can start?",
        (("Almost nothing", 0.1), ("A few open questions", 0.5), ("A lot", 0.85)),
    ),
    "stakes": (
        "If this went wrong, how bad would it be?",
        (("No big deal", 0.15), ("Annoying but fixable", 0.5), ("Seriously bad", 0.85)),
    ),
    "reversibility": (
        "Could a wrong result be undone easily?",
        (("Hard to undo", 0.15), ("With some effort", 0.5), ("Trivially", 0.9)),
    ),
    "code_intensity": (
        "How much of this is writing or changing code?",
        (("None", 0.0), ("Some", 0.5), ("Most of it", 0.9)),
    ),
    "research_intensity": (
        "How much of this is research or reading?",
        (("None", 0.0), ("Some", 0.5), ("Most of it", 0.9)),
    ),
    "tool_intensity": (
        "How much of this is running tools or commands?",
        (("None", 0.0), ("Some", 0.5), ("Most of it", 0.9)),
    ),
}

_BOOL_QUESTIONS: dict[str, str] = {
    "production_change_required": "Will this touch anything real people use or share?",
    "privacy_restricted": "Does this involve private or sensitive data?",
}


def build_questions() -> dict[str, dict[str, Any]]:
    """The full intake profile as one System One question set (plain dicts,
    so tests and alternate clients need no SDK)."""
    questions: dict[str, dict[str, Any]] = {
        "intent": {
            "type": "choice",
            "instructions": "What kind of work is being asked for",
            "criteria": dict(_INTENT_CRITERIA),
        }
    }
    for field, (instructions, criteria) in _SCORE_FIELDS.items():
        questions[field] = {
            "type": "score",
            "instructions": instructions,
            "criteria": list(criteria),
        }
    for field, statement in _NOUL_FIELDS.items():
        questions[field] = {"type": "noul", "instructions": statement}
    return questions


def _answer(answers: Mapping[str, Any], name: str, key: str, default: Any = None) -> Any:
    value = answers.get(name)
    if value is None:
        return default
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def fold_answers(
    answers: Mapping[str, Any], *, ask_threshold: float = ASK_THRESHOLD
) -> tuple[dict[str, Any], list[tuple[str, float]]]:
    """Turn one call's answers into (profile draft, uncertain fields).

    Uncertain fields are (name, certainty) with certainty < ask_threshold,
    the candidates for a clarifying question. Intent below threshold is
    simply left out of the draft — the mode router owns that default.
    """
    draft: dict[str, Any] = {}
    uncertain: list[tuple[str, float]] = []

    choice = _answer(answers, "intent", "choice")
    confidence = float(_answer(answers, "intent", "confidence", 0.0) or 0.0)
    if choice is not None and confidence >= ask_threshold:
        with contextlib.suppress(ValueError):
            draft["intent"] = TaskIntent(str(choice))

    for field, (_, criteria) in _SCORE_FIELDS.items():
        score = _answer(answers, field, "score")
        if score is None:
            continue
        span = max(1, len(criteria) - 1)
        draft[field] = min(1.0, max(0.0, float(score) / span))
        certainty = float(_answer(answers, field, "confidence", 0.0) or 0.0)
        if certainty < ask_threshold:
            uncertain.append((field, certainty))

    for field in _NOUL_FIELDS:
        noul = _answer(answers, field, "noul")
        if noul is None:
            continue
        p = min(1.0, max(0.0, float(noul)))
        draft[field] = p >= 0.5
        certainty = abs(p - 0.5) * 2  # 0.5 = coin flip, 0/1 = certain
        if certainty < ask_threshold:
            uncertain.append((field, certainty))

    return draft, uncertain


def _question_for(field: str, drafted: Any) -> IntakeQuestion | None:
    if field in _FLOAT_QUESTIONS:
        prompt, options = _FLOAT_QUESTIONS[field]
        choices = tuple(
            IntakeChoice(label=label, sets={field: value}) for label, value in options
        )
        values = [value for _, value in options]
        anchor = float(drafted) if isinstance(drafted, (int, float)) else 0.5
        recommended = min(range(len(values)), key=lambda i: abs(values[i] - anchor))
        return IntakeQuestion(id=field, prompt=prompt, choices=choices, recommended=recommended)
    if field in _BOOL_QUESTIONS:
        choices = (
            IntakeChoice(label="Yes", sets={field: True}),
            IntakeChoice(label="No", sets={field: False}),
            IntakeChoice(label="Not sure", sets={}),
        )
        recommended = 0 if drafted is True else 1
        return IntakeQuestion(
            id=field, prompt=_BOOL_QUESTIONS[field], choices=choices, recommended=recommended
        )
    return None


def build_intake_result(
    answers: Mapping[str, Any],
    *,
    ask_threshold: float = ASK_THRESHOLD,
    max_questions: int = MAX_QUESTIONS,
) -> IntakeResult:
    draft, uncertain = fold_answers(answers, ask_threshold=ask_threshold)
    uncertain.sort(key=lambda item: item[1])
    questions: list[IntakeQuestion] = []
    for field, _ in uncertain:
        if len(questions) >= max_questions:
            break
        question = _question_for(field, draft.get(field))
        if question is not None:
            questions.append(question)
    # Jev cannot restate the objective in prose; the user's wording stands.
    return IntakeResult(
        restated_objective="", profile_draft=draft, questions=tuple(questions)
    )


class SystemOneIntakeClient:
    """Thin client over typesafe-sdk: converts the plain-dict question spec
    into SDK question objects and returns the response's answers mapping."""

    def __init__(self) -> None:
        try:
            from typesafe_sdk import Choice, Noul, Score, TypeSafeClient
        except ImportError as exc:
            from icm_harness.kernel.errors import IntegrationUnavailable

            raise IntegrationUnavailable(
                "Install extras: pip install 'icm-production-harness[systemone]'"
            ) from exc
        if not os.environ.get("TYPESAFE_API_KEY"):
            from icm_harness.kernel.errors import IntegrationUnavailable

            raise IntegrationUnavailable(
                "Set TYPESAFE_API_KEY (create one at console.typesafe.ai/keys)"
            )
        self._choice, self._score, self._noul = Choice, Score, Noul
        self._client = TypeSafeClient()

    def system_one(self, *, state: str, questions: Mapping[str, Mapping[str, Any]]):
        converted: dict[str, Any] = {}
        for name, spec in questions.items():
            kind = spec["type"]
            if kind == "choice":
                converted[name] = self._choice(
                    instructions=spec["instructions"], criteria=spec["criteria"]
                )
            elif kind == "score":
                converted[name] = self._score(
                    instructions=spec["instructions"], criteria=spec["criteria"]
                )
            else:
                converted[name] = self._noul(instructions=spec["instructions"])
        return self._client.system_one(state=state, questions=converted).answers


def propose_intake(
    objective: str,
    *,
    env_facts: Mapping[str, Any] | None = None,
    client: Any | None = None,
    ask_threshold: float = ASK_THRESHOLD,
    max_questions: int = MAX_QUESTIONS,
) -> IntakeResult:
    """Profile a plain-English request through Jev.

    `client.system_one(state=..., questions=...) -> answers mapping` is
    injectable for tests; the default builds :class:`SystemOneIntakeClient`.
    Raises on transport/setup failure; callers fall back to the CLI intake
    path so this adapter is never a hard gate.
    """
    state = f"The request:\n{objective}"
    if env_facts:
        facts = json.dumps(dict(env_facts), sort_keys=True)
        state += f"\n\nWhat we can see about the workspace:\n{facts}"
    answers = (client or SystemOneIntakeClient()).system_one(
        state=state, questions=build_questions()
    )
    return build_intake_result(
        answers, ask_threshold=ask_threshold, max_questions=max_questions
    )
