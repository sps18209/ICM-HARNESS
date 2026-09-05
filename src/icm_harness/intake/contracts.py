"""Data shapes the intake step produces. Pure — no I/O, no model calls."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class IntakeChoice:
    """One answer to an intake question. `sets` names the TaskProfile fields this
    choice pins and to what value — so the answer→signal mapping is declared up
    front and applied verbatim, never re-scored after the fact."""

    label: str
    sets: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IntakeQuestion:
    id: str
    prompt: str
    choices: tuple[IntakeChoice, ...]
    recommended: int = 0  # index into `choices`


@dataclass(frozen=True, slots=True)
class IntakeResult:
    """What the intake LLM returns: a plain-English restatement for
    confirmation, its best-guess profile fields, and the questions to ask."""

    restated_objective: str
    profile_draft: Mapping[str, Any]
    questions: tuple[IntakeQuestion, ...]
