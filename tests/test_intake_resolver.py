"""test_intake_resolver.py — the shared intake-proposer resolver.

`resolve_intake_proposer` is the single place that decides which engine shapes a
request (TypeSafe Jev vs claude-cli), honoring `[intake] profiler` and an
optional override, with Jev falling back to claude-cli both when it isn't ready
and when a ready call fails. All three front-ends route through it, so these
tests pin that selection precisely — faking readiness and the two proposers so
nothing here needs a live `claude` or the TypeSafe SDK.
"""
from __future__ import annotations

from types import SimpleNamespace

import icm_harness.application.intake as resolver
import icm_harness.integrations.typesafe as typesafe
from icm_harness import intake
from icm_harness.application import resolve_intake_proposer


def _cfg(*, profiler="claude-cli", provider="claude-cli", executable="claude", ask_threshold=0.75):
    return SimpleNamespace(
        intake=SimpleNamespace(profiler=profiler, ask_threshold=ask_threshold),
        agent=SimpleNamespace(provider=provider, executable=executable),
    )


def _fake_claude(monkeypatch, sentinel="claude-result"):
    calls = {}

    def _propose(objective, *, env_facts=None, executable=None, model=None):
        calls.update(objective=objective, executable=executable, model=model)
        return sentinel

    monkeypatch.setattr(intake, "propose", _propose)
    monkeypatch.setattr(resolver.shutil, "which", lambda _exe: "/usr/bin/claude")
    return calls


# --- selection --------------------------------------------------------------


def test_claude_cli_selected_by_default(monkeypatch):
    _fake_claude(monkeypatch)
    resolved = resolve_intake_proposer(_cfg(), ".", model="m")
    assert resolved is not None
    propose, label = resolved
    assert label == "claude-cli"
    assert propose("hi") == "claude-result"


def test_claude_proposer_passes_executable_and_model(monkeypatch):
    calls = _fake_claude(monkeypatch)
    propose, _ = resolve_intake_proposer(_cfg(executable="claude-x"), ".", model="haiku")
    propose("objective text")
    assert calls == {"objective": "objective text", "executable": "claude-x", "model": "haiku"}


def test_typesafe_selected_when_ready(monkeypatch):
    monkeypatch.setattr(resolver, "_typesafe_ready", lambda _root: True)
    monkeypatch.setattr(typesafe, "propose_intake",
                        lambda objective, *, env_facts=None, ask_threshold=None: "jev-result")
    propose, label = resolve_intake_proposer(_cfg(profiler="typesafe"), ".")
    assert label == "typesafe"
    assert propose("x") == "jev-result"


def test_typesafe_not_ready_falls_back_to_claude_with_note(monkeypatch):
    _fake_claude(monkeypatch)
    monkeypatch.setattr(resolver, "_typesafe_ready", lambda _root: False)
    notes = []
    propose, label = resolve_intake_proposer(
        _cfg(profiler="typesafe"), ".", on_note=notes.append
    )
    assert label == "claude-cli"
    assert propose("x") == "claude-result"
    assert notes and "not ready" in notes[0]


def test_flag_override_beats_config(monkeypatch):
    # config says claude-cli, the flag asks for typesafe → typesafe (it's ready).
    monkeypatch.setattr(resolver, "_typesafe_ready", lambda _root: True)
    monkeypatch.setattr(typesafe, "propose_intake",
                        lambda objective, *, env_facts=None, ask_threshold=None: "jev-result")
    _, label = resolve_intake_proposer(_cfg(profiler="claude-cli"), ".", profiler="typesafe")
    assert label == "typesafe"


def test_flag_override_can_force_claude_over_typesafe_config(monkeypatch):
    _fake_claude(monkeypatch)
    # typesafe is ready, but the flag forces claude-cli → claude, no typesafe probe needed.
    monkeypatch.setattr(resolver, "_typesafe_ready", lambda _root: True)
    _, label = resolve_intake_proposer(_cfg(profiler="typesafe"), ".", profiler="claude-cli")
    assert label == "claude-cli"


def test_none_when_nothing_available(monkeypatch):
    monkeypatch.setattr(resolver, "_typesafe_ready", lambda _root: False)
    monkeypatch.setattr(resolver.shutil, "which", lambda _exe: None)
    assert resolve_intake_proposer(_cfg(profiler="typesafe"), ".") is None
    assert resolve_intake_proposer(_cfg(provider="dry-run"), ".") is None


def test_typesafe_call_failure_falls_back_to_claude_at_runtime(monkeypatch):
    calls = _fake_claude(monkeypatch)  # claude is available for fallback
    monkeypatch.setattr(resolver, "_typesafe_ready", lambda _root: True)

    def _boom(objective, *, env_facts=None, ask_threshold=None):
        raise RuntimeError("jev network down")

    monkeypatch.setattr(typesafe, "propose_intake", _boom)
    notes = []
    propose, label = resolve_intake_proposer(
        _cfg(profiler="typesafe"), ".", on_note=notes.append
    )
    assert label == "typesafe"  # selected engine is still Jev
    assert propose("x") == "claude-result"  # but a failed call fell back
    assert calls["objective"] == "x"
    assert notes and "failed" in notes[0]


def test_typesafe_call_failure_raises_when_no_claude_fallback(monkeypatch):
    monkeypatch.setattr(resolver, "_typesafe_ready", lambda _root: True)
    monkeypatch.setattr(resolver.shutil, "which", lambda _exe: None)  # no claude

    def _boom(objective, *, env_facts=None, ask_threshold=None):
        raise RuntimeError("jev down")

    monkeypatch.setattr(typesafe, "propose_intake", _boom)
    propose, label = resolve_intake_proposer(_cfg(profiler="typesafe"), ".")
    assert label == "typesafe"
    try:
        propose("x")
    except RuntimeError as exc:
        assert "jev down" in str(exc)
    else:
        raise AssertionError("expected the failure to propagate with no fallback")
