"""The intake LLM call and the deterministic profile finalizer.

`propose()` turns a plain-English request into an `IntakeResult` (a proposed
profile + 2–4 plain questions). `finalize()` deterministically folds the user's
answers onto the draft and produces a validated `TaskProfile`. The model
proposes; this code decides — the router downstream stays free of any model.
"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from icm_harness.agents import extract_json, unwrap_envelope
from icm_harness.intake.contracts import IntakeChoice, IntakeQuestion, IntakeResult
from icm_harness.kernel.contracts import TaskIntent, TaskProfile

# Fields the intake step is allowed to set. Objective is handled separately
# (we keep the user's own words); latency/budget/capabilities are operator
# concerns left to flags.
_FLOAT_FIELDS = (
    "specification_clarity",
    "epistemic_uncertainty",
    "stakes",
    "reversibility",
    "code_intensity",
    "research_intensity",
    "tool_intensity",
)
_BOOL_FIELDS = ("production_change_required", "privacy_restricted")

MAX_QUESTIONS = 4

# The intake CLI call needs no tools — it is pure classification — so every
# tool is denied. That also keeps a stray model from touching the filesystem
# during what the user experiences as "answering a couple of questions".
_INTAKE_DENIED_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit", "Bash")

_SCHEMA = {
    "type": "object",
    "required": ["restated_objective", "profile_draft", "questions"],
    "properties": {
        "restated_objective": {"type": "string"},
        "profile_draft": {
            "type": "object",
            "properties": {
                "intent": {"enum": [i.value for i in TaskIntent]},
                **{f: {"type": "number"} for f in _FLOAT_FIELDS},
                **{f: {"type": "boolean"} for f in _BOOL_FIELDS},
            },
        },
        "questions": {
            "type": "array",
            "maxItems": MAX_QUESTIONS,
            "items": {
                "type": "object",
                "required": ["id", "prompt", "choices"],
                "properties": {
                    "id": {"type": "string"},
                    "prompt": {"type": "string"},
                    "recommended": {"type": "integer"},
                    "choices": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["label"],
                            "properties": {
                                "label": {"type": "string"},
                                "sets": {"type": "object"},
                            },
                        },
                    },
                },
            },
        },
    },
}

_SYSTEM = """\
You are the intake step of an AI engineering harness. A person has described, in
plain language, something they want done. Your job is to turn that into a task
profile and a SHORT guided conversation — never to do the work itself.

The person may know nothing about code. Ask 2 to 4 plain-English questions, each
with 2 to 4 concrete multiple-choice answers, no jargon, no numbers. Choose the
questions that actually matter for THIS request; skip anything you can already
infer.

Every profile signal is a number from 0 to 1 (or a yes/no). They drive how the
harness routes the work:
- specification_clarity: how clearly the person already knows what they want.
- epistemic_uncertainty: how much is genuinely unknown / needs figuring out.
- stakes: how much damage a mistake would do.
- reversibility: how easily a wrong result can be undone (1 = trivially).
- production_change_required: will this touch real, live, or shared systems?
- code_intensity / research_intensity / tool_intensity: how much of each the
  work needs.
- intent: one of auto, build, investigate, decide, review, quick.

For each answer CHOICE, put the profile fields it implies in its "sets" object,
so picking it pins those signals. Example: an answer "Something real people will
use" might set {"stakes": 0.7, "production_change_required": true}. "Not sure"
usually sets nothing.

Fill "profile_draft" with your best inference for every field even before the
questions are answered. Restate the objective in one plain sentence.

Return ONLY a JSON object matching the supplied schema — no prose, no fences.
"""


def _default_agent_fn(prompt: str, *, executable: str, model: str | None) -> str:
    """Run the intake prompt through the `claude` CLI, no tools, and return the
    model's text. Kept tiny and synchronous — intake is one classification call,
    not a stage."""
    command = [
        executable,
        "--print",
        "--output-format",
        "json",
        "--permission-mode",
        "plan",
        "--disallowed-tools",
        *_INTAKE_DENIED_TOOLS,
    ]
    if model and model != "default":
        command.extend(("--model", model))
    completed = subprocess.run(
        command,
        input=prompt,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or f"exit {completed.returncode}").strip()
        raise RuntimeError(detail[-2000:])
    return unwrap_envelope(completed.stdout.strip(), error=RuntimeError)


def _build_prompt(objective: str, env_facts: Mapping[str, Any]) -> str:
    facts = json.dumps(dict(env_facts), sort_keys=True)
    schema = json.dumps(_SCHEMA, indent=2, sort_keys=True)
    return (
        _SYSTEM
        + f"\n\nThe request:\n{objective}\n\nWhat we can see about the workspace:\n{facts}"
        + f"\n\nThe supplied schema is:\n{schema}"
    )


def _parse(payload: Mapping[str, Any]) -> IntakeResult:
    draft_in = payload.get("profile_draft") or {}
    if not isinstance(draft_in, Mapping):
        draft_in = {}
    draft = _clean_profile_fields(draft_in)

    questions: list[IntakeQuestion] = []
    for q in (payload.get("questions") or [])[:MAX_QUESTIONS]:
        if not isinstance(q, Mapping):
            continue
        choices = []
        for c in q.get("choices") or []:
            if not isinstance(c, Mapping) or "label" not in c:
                continue
            sets = c.get("sets") or {}
            choices.append(
                IntakeChoice(label=str(c["label"]), sets=_clean_profile_fields(sets))
            )
        if not choices:
            continue
        rec = q.get("recommended", 0)
        rec = rec if isinstance(rec, int) and 0 <= rec < len(choices) else 0
        questions.append(
            IntakeQuestion(
                id=str(q.get("id") or f"q{len(questions) + 1}"),
                prompt=str(q.get("prompt") or ""),
                choices=tuple(choices),
                recommended=rec,
            )
        )
    return IntakeResult(
        restated_objective=str(payload.get("restated_objective") or "").strip(),
        profile_draft=draft,
        questions=tuple(questions),
    )


def _clean_profile_fields(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only recognized fields, coerce/clamp them. Unknown keys dropped."""
    out: dict[str, Any] = {}
    for field_name in _FLOAT_FIELDS:
        if field_name in raw:
            with contextlib.suppress(TypeError, ValueError):
                out[field_name] = min(1.0, max(0.0, float(raw[field_name])))
    for field_name in _BOOL_FIELDS:
        if field_name in raw:
            out[field_name] = bool(raw[field_name])
    if "intent" in raw:
        with contextlib.suppress(ValueError):
            out["intent"] = TaskIntent(str(raw["intent"]))
    return out


def propose(
    objective: str,
    *,
    env_facts: Mapping[str, Any] | None = None,
    agent_fn: Callable[[str], str] | None = None,
    executable: str = "claude",
    model: str | None = None,
) -> IntakeResult:
    """Ask the intake LLM for a proposed profile + questions.

    `agent_fn(prompt) -> text` is injectable for tests; the default runs the
    `claude` CLI. Raises on transport/parse failure; callers fall back to
    flag-based defaults so intake is never a hard gate.
    """
    prompt = _build_prompt(objective, env_facts or {})
    if agent_fn is None:
        text = _default_agent_fn(prompt, executable=executable, model=model)
    else:
        text = agent_fn(prompt)
    payload = json.loads(extract_json(text))
    if not isinstance(payload, Mapping):
        raise ValueError("intake result was not a JSON object")
    return _parse(payload)


def finalize(
    objective: str, result: IntakeResult, answers: Sequence[int]
) -> TaskProfile:
    """Fold the chosen answers onto the draft and build a validated TaskProfile.

    Deterministic: starts from the LLM's draft, applies each answered choice's
    declared `sets`, coerces/clamps, and keeps the user's ORIGINAL objective
    wording (the restatement is for on-screen confirmation only).
    """
    merged: dict[str, Any] = dict(result.profile_draft)
    for question, choice_index in zip(result.questions, answers, strict=False):
        if 0 <= choice_index < len(question.choices):
            merged.update(question.choices[choice_index].sets)

    kwargs: dict[str, Any] = {"objective": objective}
    intent = merged.get("intent")
    if isinstance(intent, TaskIntent):
        kwargs["intent"] = intent
    for field_name in _FLOAT_FIELDS:
        if field_name in merged:
            kwargs[field_name] = min(1.0, max(0.0, float(merged[field_name])))
    for field_name in _BOOL_FIELDS:
        if field_name in merged:
            kwargs[field_name] = bool(merged[field_name])
    return TaskProfile(**kwargs)
