"""test_intake_picker.py — the CLI question picker's shortcut-key handling.

The raw single-keypress transport (`_read_key`) touches termios and only runs at
a real TTY, so it is not exercised here; the picker's *interpretation* of keys is
factored out behind an injectable `read`, and that is what these tests drive with
a scripted key sequence. Covers number selection, Enter = suggestion, `a` =
accept all (fills the rest and stops), `q` = cancel, and re-ask on a bad key.
"""
from __future__ import annotations

from icm_harness.cli.app import _ACCEPT_ALL, _CANCEL, _ask_intake_questions, _read_choice
from icm_harness.intake.contracts import IntakeChoice, IntakeQuestion, IntakeResult


def _reader(keys):
    it = iter(keys)
    return lambda _prompt: next(it)


def _result():
    return IntakeResult(
        restated_objective="r",
        profile_draft={},
        questions=(
            IntakeQuestion(
                id="who", prompt="Who for?",
                choices=(IntakeChoice("me", {}), IntakeChoice("users", {})), recommended=0,
            ),
            IntakeQuestion(
                id="how", prompt="How?",
                choices=(IntakeChoice("a", {}), IntakeChoice("b", {}), IntakeChoice("c", {})),
                recommended=1,
            ),
        ),
    )


# --- _read_choice -----------------------------------------------------------


def test_number_key_selects_that_choice():
    assert _read_choice(3, 1, read=_reader(["2"])) == 1


def test_enter_takes_the_suggestion():
    assert _read_choice(3, 1, read=_reader([""])) == 1


def test_a_is_accept_all_and_q_is_cancel():
    assert _read_choice(3, 1, read=_reader(["a"])) == _ACCEPT_ALL
    assert _read_choice(3, 1, read=_reader(["q"])) == _CANCEL


def test_out_of_range_key_reasks(capsys):
    # '9' is out of range for 2 choices → re-ask, then '1' selects index 0.
    assert _read_choice(2, 0, read=_reader(["9", "1"])) == 0
    assert "1–2" in capsys.readouterr().out


def test_eof_falls_back_to_the_suggestion():
    def _raises(_prompt):
        raise EOFError

    assert _read_choice(2, 1, read=_raises) == 1


# --- _ask_intake_questions --------------------------------------------------


def test_collects_numbered_answers():
    # q1 → '2' (index 1), q2 → '1' (index 0).
    assert _ask_intake_questions(_result(), read=_reader(["2", "1"])) == [1, 0]


def test_enter_runs_accept_the_suggestions():
    assert _ask_intake_questions(_result(), read=_reader(["", ""])) == [0, 1]


def test_accept_all_fills_remaining_with_suggestions():
    # 'a' on the first question accepts the suggestion for it AND q2, then stops.
    assert _ask_intake_questions(_result(), read=_reader(["a"])) == [0, 1]


def test_cancel_returns_none():
    assert _ask_intake_questions(_result(), read=_reader(["q"])) is None
