"""Resolve which intake proposer to run, from config and an optional override.

Every front-end — `icm new`, the web console, and `icm intake-eval` — shapes a
plain-English objective the same way, and this is the one place that decides
how: the TypeSafe Jev profiler when `[intake] profiler = "typesafe"` is set and
actually reachable (its SDK installed and an API key discoverable), otherwise
the claude-cli proposer. A `profiler` argument overrides the configured choice
(the CLI/eval flag, layered on top). Jev falls back to claude-cli — both at
selection time, when it isn't ready, and at call time, if a ready call fails —
so intake is always an assist, never a gate.

This lives in `application`, NOT in the CORE `intake` module, because it reaches
the `integrations` adapter, which Rule A forbids CORE from importing. The
`integrations.typesafe` import is kept lazy so the adapter stays an optional
dependency.
"""
from __future__ import annotations

import importlib.util
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from icm_harness import intake
from icm_harness.config import HarnessConfig

# A proposer: objective -> IntakeResult (the one shaping call).
ProposeFn = Callable[[str], Any]
# An optional one-line notice sink (e.g. the CLI prints fallbacks to stderr).
NoteFn = Callable[[str], None]

VALID_PROFILERS = ("claude-cli", "typesafe")


def _typesafe_ready(root: str | Path) -> bool:
    """Jev can run here: its SDK is importable and an API key is discoverable.
    A probe, so selection is deterministic — a ready call that later fails at
    runtime still falls back (see `resolve_intake_proposer`)."""
    try:
        from icm_harness.integrations.typesafe import api_key_source
    except Exception:  # noqa: BLE001 — adapter is an optional dependency
        return False
    if importlib.util.find_spec("typesafe_sdk") is None:
        return False
    return api_key_source(root) is not None


def _claude_ready(config: HarnessConfig) -> bool:
    return (
        config.agent.provider == "claude-cli"
        and shutil.which(config.agent.executable) is not None
    )


def resolve_intake_proposer(
    config: HarnessConfig,
    root: str | Path = ".",
    *,
    env_facts: Mapping[str, Any] | None = None,
    profiler: str | None = None,
    model: str | None = None,
    on_note: NoteFn | None = None,
) -> tuple[ProposeFn, str] | None:
    """Return `(propose, profiler_label)` or None when nothing can shape intake.

    `profiler` (when given) overrides `config.intake.profiler`. TypeSafe Jev is
    chosen only when ready; otherwise it falls back to claude-cli and `on_note`
    is called once with the reason. When Jev IS chosen, the returned proposer
    still falls back to claude-cli if a call fails at runtime and claude is
    available, matching the CLI's long-standing behavior.
    """
    facts = dict(env_facts or {})
    chosen = (profiler or config.intake.profiler or "claude-cli").lower()

    def _claude(objective: str):
        return intake.propose(
            objective, env_facts=facts, executable=config.agent.executable, model=model
        )

    if chosen == "typesafe":
        if _typesafe_ready(root):
            claude_ok = _claude_ready(config)

            def _typesafe(objective: str):
                from icm_harness.integrations.typesafe import propose_intake

                try:
                    return propose_intake(
                        objective, env_facts=facts, ask_threshold=config.intake.ask_threshold
                    )
                except Exception as exc:  # noqa: BLE001 — assist, never a gate
                    if not claude_ok:
                        raise
                    if on_note is not None:
                        on_note(f"typesafe intake failed ({exc}); using claude-cli")
                    return _claude(objective)

            return _typesafe, "typesafe"
        if on_note is not None:
            on_note("typesafe profiler not ready (SDK or API key missing); using claude-cli")

    if _claude_ready(config):
        return _claude, "claude-cli"
    return None
