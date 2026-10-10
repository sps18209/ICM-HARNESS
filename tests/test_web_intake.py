"""test_web_intake.py — the operator console's guided-intake HTTP surface.

Drives a real `OperatorServer` in-process (threaded, loopback, no token) so the
request path — JSON body parsing, the `/api/intake/propose` endpoint, and the
`/api/rounds` intake-finalize branch — is exercised exactly as the browser hits
it. The intake model call is faked by monkeypatching `icm_harness.intake.propose`
(and `shutil.which` in the server module, so the claude-CLI gate passes without
a real binary), so nothing here depends on a live `claude`.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from threading import Thread

import pytest

from icm_harness import intake
from icm_harness.config import write_default_config
from icm_harness.intake.contracts import IntakeChoice, IntakeQuestion, IntakeResult
from icm_harness.web import server as web_server


def _init(root: Path) -> None:
    (root / "0_Context_Wiki").mkdir(parents=True)
    (root / "2_Working_State").mkdir(parents=True)
    (root / "2_Working_State/CURRENT").write_text("NONE\n", encoding="utf-8")
    (root / ".harness/runtime").mkdir(parents=True)
    write_default_config(root / ".harness/config.toml")


# A canned proposal: one question whose two choices pin opposite stakes, so a
# chosen answer demonstrably reaches the finalized profile.
_PROPOSAL = IntakeResult(
    restated_objective="Build a small running-log app.",
    profile_draft={"specification_clarity": 0.4, "code_intensity": 0.7},
    questions=(
        IntakeQuestion(
            id="surface",
            prompt="Who is this for?",
            choices=(
                IntakeChoice(label="Just me", sets={"stakes": 0.2}),
                IntakeChoice(label="Real users", sets={"stakes": 0.8}),
            ),
            recommended=0,
        ),
    ),
)


class _Server:
    def __init__(self, root: Path):
        self.runtime = web_server.WebRuntime(root)
        self.httpd = web_server.OperatorServer(
            ("127.0.0.1", 0), web_server.OperatorHandler, runtime=self.runtime, token=None
        )
        self.port = self.httpd.server_port
        self.thread = Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def post(self, path: str, body: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server(tmp_path):
    _init(tmp_path)
    srv = _Server(tmp_path)
    try:
        yield srv
    finally:
        srv.close()


def test_propose_returns_questions_when_cli_available(server, monkeypatch):
    monkeypatch.setattr(web_server.shutil, "which", lambda _exe: "/usr/bin/claude")
    monkeypatch.setattr(intake, "propose", lambda objective, **kw: _PROPOSAL)
    status, payload = server.post("/api/intake/propose", {"objective": "a running log"})
    assert status == 200
    assert payload["applicable"] is True
    proposal = payload["proposal"]
    assert proposal["restated_objective"] == "Build a small running-log app."
    assert len(proposal["questions"]) == 1
    assert proposal["questions"][0]["choices"][1]["sets"]["stakes"] == 0.8


def test_propose_degrades_gracefully_without_cli(server, monkeypatch):
    # No claude binary on PATH → not a 500, but an honest applicable:false so the
    # panel can fall back to the manual fields.
    monkeypatch.setattr(web_server.shutil, "which", lambda _exe: None)
    status, payload = server.post("/api/intake/propose", {"objective": "anything"})
    assert status == 200
    assert payload["applicable"] is False
    assert "claude" in payload["reason"]


def test_propose_degrades_when_model_call_fails(server, monkeypatch):
    monkeypatch.setattr(web_server.shutil, "which", lambda _exe: "/usr/bin/claude")

    def _boom(objective, **kw):
        raise RuntimeError("transport exploded")

    monkeypatch.setattr(intake, "propose", _boom)
    status, payload = server.post("/api/intake/propose", {"objective": "anything"})
    assert status == 200
    assert payload["applicable"] is False


def test_propose_requires_objective(server):
    status, payload = server.post("/api/intake/propose", {"objective": "   "})
    assert status == 400
    assert "objective is required" in payload["error"]


def test_create_round_finalizes_intake_answers(server):
    # The browser echoes the proposal it received plus the chosen answers; the
    # server finalizes deterministically. Choosing "Real users" (index 1) must
    # push stakes to 0.8 on the created round's profile.
    proposal = intake.result_to_payload(_PROPOSAL)
    status, payload = server.post(
        "/api/rounds",
        {"objective": "Build a running log", "intake": proposal, "answers": [1], "run": False},
    )
    assert status == 201
    assert payload["objective"] == "Build a running log"
    assert payload["profile"]["stakes"] == 0.8
    # The user's ORIGINAL wording is kept, not the model's restatement.
    assert payload["objective"] != _PROPOSAL.restated_objective


def test_create_round_rejects_bad_answers(server):
    proposal = intake.result_to_payload(_PROPOSAL)
    status, payload = server.post(
        "/api/rounds",
        {"objective": "x", "intake": proposal, "answers": "not-a-list", "run": False},
    )
    assert status == 400
    assert "answers" in payload["error"]


def test_create_round_manual_path_still_works(server):
    # No `intake` key → the explicit-fields path (Advanced form / API clients).
    status, payload = server.post(
        "/api/rounds",
        {"objective": "manual round", "stakes": 0.3, "intent": "build", "run": False},
    )
    assert status == 201
    assert payload["objective"] == "manual round"
    assert payload["profile"]["stakes"] == 0.3
