"""Public interface (barrel) for the ``intake`` module.

Intake sits UPSTREAM of routing: it turns a plain-English request into a
`TaskProfile` via a short LLM-guided conversation, so a person needs no flags
and no code knowledge. Routing then decides the mode from that profile,
deterministically, exactly as before.

Other modules import these symbols from ``icm_harness.intake`` — never from its
private submodules (enforced by ``scripts/validate_architecture.py``). Imports
are lazy (PEP 562) so declaring the barrel triggers no eager import.
"""
from __future__ import annotations

import importlib
from typing import Any

_PUBLIC: dict[str, str] = {
    "propose": "agent",
    "finalize": "agent",
    "MAX_QUESTIONS": "agent",
    "IntakeResult": "contracts",
    "IntakeQuestion": "contracts",
    "IntakeChoice": "contracts",
}

__all__ = sorted(_PUBLIC)


def __getattr__(name: str) -> Any:
    module = _PUBLIC.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(f"icm_harness.intake.{module}"), name)


def __dir__() -> list[str]:
    return list(__all__)
