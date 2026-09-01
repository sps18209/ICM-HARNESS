from __future__ import annotations

import socket
import time
from pathlib import Path

import pytest

from icm_harness.cli import app
from icm_harness.cli import server_control as sc
from icm_harness.config import write_default_config


def _init(root: Path) -> None:
    (root / "0_Context_Wiki").mkdir(parents=True)
    (root / "2_Working_State").mkdir(parents=True)
    (root / "2_Working_State/CURRENT").write_text("NONE\n", encoding="utf-8")
    (root / ".harness/runtime").mkdir(parents=True)
    write_default_config(root / ".harness/config.toml")


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


# --- shell-init -------------------------------------------------------------


def test_shell_init_emits_functions_for_bash_and_zsh(capsys):
    for shell in ("bash", "zsh"):
        assert app.main(["shell-init", shell]) == 0
        out = capsys.readouterr().out
        for fn in ("icm-up()", "icm-down()", "icm-toggle()", "icm-new()", "icm-pick()"):
            assert fn in out


def test_shell_init_rejects_unsupported_shell(monkeypatch, capsys):
    monkeypatch.setenv("SHELL", "/usr/bin/fish")
    # No positional given → falls back to $SHELL, which is unsupported.
    assert app.main(["shell-init"]) == 2
    assert "bash and zsh" in capsys.readouterr().err


# --- background server lifecycle -------------------------------------------


def test_server_start_status_stop(tmp_path):
    _init(tmp_path)
    port = _free_port()
    try:
        started = sc.start(tmp_path, "127.0.0.1", port)
        assert started["healthy"] is True
        assert sc.state_path(tmp_path).exists()

        running, state = sc.is_running(tmp_path)
        assert running and state and state["port"] == port

        info = sc.status(tmp_path)
        assert info["running"] and info["healthy"] and info["url"].endswith(str(port))

        # Starting again is a no-op that reports the existing server.
        again = sc.start(tmp_path, "127.0.0.1", port)
        assert again.get("already_running") is True
    finally:
        result = sc.stop(tmp_path)
        assert result["stopped"] is True

    # After stop, state is cleared and the port frees up.
    assert not sc.state_path(tmp_path).exists()
    assert sc.status(tmp_path) == {"running": False}


def test_server_toggle_round_trips(tmp_path):
    _init(tmp_path)
    port = _free_port()
    try:
        up = sc.toggle(tmp_path, "127.0.0.1", port)
        assert up["action"] == "started"
        assert sc.status(tmp_path)["running"] is True
        down = sc.toggle(tmp_path, "127.0.0.1", port)
        assert down["action"] == "stopped"
        assert sc.status(tmp_path)["running"] is False
    finally:
        sc.stop(tmp_path)


def test_server_start_rejects_non_loopback_without_token(tmp_path, monkeypatch):
    _init(tmp_path)
    monkeypatch.delenv("ICM_WEB_TOKEN", raising=False)
    with pytest.raises(ValueError, match="ICM_WEB_TOKEN"):
        sc.start(tmp_path, "0.0.0.0", _free_port())


def test_stop_without_server_is_safe(tmp_path):
    _init(tmp_path)
    result = sc.stop(tmp_path)
    assert result["stopped"] is False
    # A stale state file with a dead pid must not report running.
    sc.state_path(tmp_path).write_text('{"pid": 999999, "url": "http://x", "port": 1}\n')
    assert sc.is_running(tmp_path)[0] is False
    time.sleep(0)  # no-op; keeps the intent explicit
