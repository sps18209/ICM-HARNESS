"""Background lifecycle for the operator console.

`icm serve` runs in the foreground; this module lets `icm server
{start,stop,status,toggle,restart}` run it detached and track it through a small
JSON state file at ``.harness/runtime/server.json``. The VS Code extension and
shell helpers can rely on the same state.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def state_path(root: Path) -> Path:
    return root / ".harness/runtime/server.json"


def log_path(root: Path) -> Path:
    return root / ".harness/runtime/server.log"


def read_state(root: Path) -> dict | None:
    path = state_path(root)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def is_running(root: Path) -> tuple[bool, dict | None]:
    state = read_state(root)
    if not state:
        return False, None
    return _pid_alive(int(state.get("pid", -1))), state


def _healthy(url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=timeout) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _write_state(root: Path, state: dict) -> None:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def start(root: Path, host: str, port: int, *, wait_seconds: float = 10.0) -> dict:
    running, state = is_running(root)
    if running and state:
        state = {**state, "already_running": True}
        return state

    if host not in LOOPBACK_HOSTS and not os.environ.get("ICM_WEB_TOKEN"):
        raise ValueError(
            "binding outside loopback requires ICM_WEB_TOKEN; keep host on 127.0.0.1 "
            "or export a token before starting"
        )

    log = log_path(root)
    log.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "icm_harness", "serve", "--host", host, "--port", str(port)]
    with open(log, "ab") as handle:
        process = subprocess.Popen(
            command,
            cwd=str(root),
            stdout=handle,
            stderr=handle,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

    url = f"http://{host}:{port}"
    state = {"pid": process.pid, "host": host, "port": port, "url": url, "healthy": False}
    _write_state(root, state)

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            state["healthy"] = False
            state["exited"] = process.returncode
            _write_state(root, state)
            return {**state, "already_running": False}
        if _healthy(url):
            state["healthy"] = True
            break
        time.sleep(0.2)
    _write_state(root, state)
    return {**state, "already_running": False}


def stop(root: Path) -> dict:
    running, state = is_running(root)
    if not state:
        return {"stopped": False, "reason": "no server is tracked"}
    pid = int(state.get("pid", -1))
    if running and pid > 0:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGTERM)
    state_path(root).unlink(missing_ok=True)
    return {"stopped": True, "pid": pid}


def status(root: Path) -> dict:
    running, state = is_running(root)
    if not state:
        return {"running": False}
    healthy = _healthy(state["url"]) if running else False
    return {**state, "running": running, "healthy": healthy}


def toggle(root: Path, host: str, port: int) -> dict:
    running, _ = is_running(root)
    if running:
        return {"action": "stopped", **stop(root)}
    return {"action": "started", **start(root, host, port)}
