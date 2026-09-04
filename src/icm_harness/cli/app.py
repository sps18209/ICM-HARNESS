from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict
from importlib import resources
from pathlib import Path
from typing import Any

import anyio

from icm_harness.application import HarnessApplication
from icm_harness.config import load_config, write_default_config
from icm_harness.kernel.contracts import TaskIntent, TaskProfile


def _root() -> Path:
    return Path.cwd().resolve()


def _application(args) -> HarnessApplication:
    return HarnessApplication(_root(), dry_run=bool(getattr(args, "dry_run", False)))


def _round_id(app: HarnessApplication, value: str | None) -> str:
    if value:
        return value
    current = app.current_round()
    if current is not None:
        return current.round_id
    recent = app.list_rounds(limit=1)
    if recent:
        return recent[0].round_id
    raise ValueError("no rounds exist; create one or pass a round id")


def _json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def _print_round(record) -> None:
    print(f"round={record.round_id}")
    print(f"status={record.status}")
    print(f"route={' -> '.join(record.route)}")
    print(f"stage={record.current_stage or '-'}")
    print(f"progress={min(record.cursor, len(record.stages))}/{len(record.stages)}")
    if record.active_gate:
        print(f"gate={record.active_gate}")
    if record.workspace_path:
        print(f"workspace={record.workspace_path}")
    if record.last_error:
        print(f"error={record.last_error}")


def cmd_init(args) -> int:
    target = Path(args.path).resolve()
    target.mkdir(parents=True, exist_ok=True)
    template = resources.files("icm_harness").joinpath("templates", "workspace")
    with resources.as_file(template) as template_path:
        shutil.copytree(template_path, target, dirs_exist_ok=True)
    (target / ".harness/runtime").mkdir(parents=True, exist_ok=True)
    write_default_config(target / ".harness/config.toml")
    print(target)
    print("initialized=.harness/config.toml")
    return 0


def _profile_from_args(args) -> TaskProfile:
    return TaskProfile(
        objective=args.objective,
        intent=TaskIntent(args.intent),
        specification_clarity=args.clarity,
        epistemic_uncertainty=args.uncertainty,
        stakes=args.stakes,
        reversibility=args.reversibility,
        production_change_required=args.production_change,
        code_intensity=args.code_intensity,
        research_intensity=args.research_intensity,
        tool_intensity=args.tool_intensity,
        privacy_restricted=args.privacy_restricted,
        latency_tolerance_ms=args.latency_ms,
        budget_usd=args.budget_usd,
        required_capabilities=frozenset(args.require_capability),
    )


def cmd_new(args) -> int:
    app = _application(args)
    record = app.create_round(_profile_from_args(args))
    if args.run:
        record = anyio.run(app.run_round, record.round_id)
    if args.json:
        _json(app.round_payload(record))
    else:
        _print_round(record)
        print(f"reason={record.route_reason}")
    return 0


def cmd_run(args) -> int:
    app = _application(args)
    round_id = _round_id(app, args.round_id)
    record = anyio.run(app.run_round, round_id)
    if args.json:
        _json(app.round_payload(record))
    else:
        _print_round(record)
    return 0 if record.status in {"active", "running", "waiting_approval", "closed"} else 1


def cmd_status(args) -> int:
    app = _application(args)
    if args.round_id:
        record = app.get_round(args.round_id)
    else:
        record = app.current_round()
        if record is None:
            print("No active round.")
            return 0
    if args.json:
        _json(app.round_payload(record))
    else:
        _print_round(record)
    return 0


def cmd_list(args) -> int:
    app = _application(args)
    rounds = app.list_rounds(limit=args.limit)
    if args.json:
        _json([app.round_payload(record) for record in rounds])
        return 0
    if not rounds:
        print("No rounds.")
        return 0
    for record in rounds:
        print(
            f"{record.round_id}\t{record.status}\t{record.current_stage or '-'}\t{record.objective}"
        )
    return 0


def cmd_events(args) -> int:
    app = _application(args)
    round_id = _round_id(app, args.round_id)
    events = app.events(round_id, after_id=args.after)
    if args.json:
        _json([asdict(event) for event in events])
        return 0
    for event in events:
        detail = event.payload.get("summary") or event.payload.get("error") or ""
        print(f"{event.id}\t{event.created_at}\t{event.kind}\t{event.stage_ref or '-'}\t{detail}")
    return 0


def cmd_artifacts(args) -> int:
    app = _application(args)
    if args.artifact_id is not None:
        record, content = app.read_artifact(args.artifact_id)
        if args.json:
            payload = asdict(record)
            payload["content"] = content
            _json(payload)
        else:
            print(content, end="" if content.endswith("\n") else "\n")
        return 0
    round_id = _round_id(app, args.round_id)
    artifacts = app.list_artifacts(round_id)
    if args.json:
        _json([asdict(record) for record in artifacts])
        return 0
    for record in artifacts:
        print(f"{record.id}\t{record.stage_ref}\t{record.name}\t{record.size} bytes")
    return 0


def cmd_approve(args) -> int:
    app = _application(args)
    record = app.approve_round(_round_id(app, args.round_id))
    if args.run:
        record = anyio.run(app.run_round, record.round_id)
    _print_round(record)
    return 0


def cmd_cancel(args) -> int:
    app = _application(args)
    _print_round(app.cancel_round(_round_id(app, args.round_id)))
    return 0


def cmd_retry(args) -> int:
    app = _application(args)
    record = app.retry_round(_round_id(app, args.round_id))
    if args.run:
        record = anyio.run(app.run_round, record.round_id)
    _print_round(record)
    return 0


def cmd_diff(args) -> int:
    app = _application(args)
    content = app.diff_round(_round_id(app, args.round_id))
    print(content or "No isolated workspace changes.")
    return 0


def cmd_promote(args) -> int:
    app = _application(args)
    record = app.promote_round(_round_id(app, args.round_id))
    _print_round(record)
    print("promoted=yes")
    return 0


def _git_repository(root: Path) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
        text=True,
        capture_output=True,
    )
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def cmd_doctor(args) -> int:
    root = _root()
    checks: list[tuple[str, bool, str]] = []
    checks.append(("python", sys.version_info >= (3, 11), sys.version.split()[0]))
    checks.append(("git", shutil.which("git") is not None, shutil.which("git") or "not found"))
    try:
        config = load_config(root)
        checks.append(("config", True, str(root / ".harness/config.toml")))
    except (OSError, ValueError) as exc:
        config = None
        checks.append(("config", False, str(exc)))
    checks.append(("workspace-writable", os.access(root, os.W_OK), str(root)))
    if config:
        executable = shutil.which(config.agent.executable)
        checks.append(("agent", executable is not None, executable or config.agent.executable))
        if config.workspace.strategy == "worktree":
            checks.append(("git-repository", _git_repository(root), str(root)))
    # Optional niceties for the shell helpers (do not fail the overall check).
    fzf = shutil.which("fzf")
    print(f"fzf: {'OK' if fzf else 'optional'} ({fzf or 'install for icm-pick'})")
    from icm_harness.cli import server_control as sc

    server = sc.status(root)
    if server.get("running"):
        print(f"server: OK ({server.get('url')})")
    else:
        print("server: down (run icm-up or `icm server start`)")
    for name, ok, detail in checks:
        print(f"{name}: {'OK' if ok else 'MISSING'} ({detail})")
    return 0 if all(ok for _, ok, _ in checks) else 1


def cmd_serve(args) -> int:
    from icm_harness.web import serve

    config = load_config(_root())
    host = args.host or config.web.host
    port = args.port or config.web.port
    serve(_root(), host=host, port=port)
    return 0


def _print_server(info: dict) -> None:
    if not info.get("running"):
        print("server: down")
        return
    health = "healthy" if info.get("healthy") else "starting"
    print(f"server: up ({health})")
    print(f"pid={info.get('pid')}")
    print(f"url={info.get('url')}")


def cmd_server(args) -> int:
    from icm_harness.cli import server_control as sc

    root = _root()
    config = load_config(root)
    host = args.host or config.web.host
    port = args.port or config.web.port
    action = args.action

    if action == "status":
        info = sc.status(root)
        if getattr(args, "url", False):
            if info.get("running") and info.get("url"):
                print(info["url"])
                return 0
            return 1
        if args.json:
            _json(info)
        else:
            _print_server(info)
        return 0 if info.get("running") else 1

    if action == "start":
        info = sc.start(root, host, port)
    elif action == "stop":
        info = sc.stop(root)
    elif action == "restart":
        sc.stop(root)
        info = sc.start(root, host, port)
    else:  # toggle
        info = sc.toggle(root, host, port)

    if args.json:
        _json(info)
    elif action == "stop":
        print("server: stopped" if info.get("stopped") else f"server: {info.get('reason')}")
    else:
        _print_server(sc.status(root))
    if action in {"start", "restart", "toggle"}:
        current = sc.status(root)
        if current.get("running") and not current.get("healthy"):
            print("warning: server started but is not answering yet; check server.log")
    return 0


def cmd_shell_init(args) -> int:
    shell = args.shell or os.path.basename(os.environ.get("SHELL", "")) or "bash"
    if shell not in {"bash", "zsh"}:
        print(f"icm: shell-init supports bash and zsh, not {shell!r}", file=sys.stderr)
        return 2
    print(SHELL_INTEGRATION)
    return 0


# Emitted by `icm shell-init`; sourced via `eval "$(icm shell-init)"`.
# POSIX-function syntax that works identically in bash and zsh.
SHELL_INTEGRATION = r"""# --- icm shell integration ---
_icm_dry_marker() { printf '%s' "${PWD}/.harness/runtime/dry_run"; }
_icm_dry_flag() { [ -f "$(_icm_dry_marker)" ] && printf -- '--dry-run'; }

_icm_open() {
  if command -v open >/dev/null 2>&1; then open "$1" >/dev/null 2>&1
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$1" >/dev/null 2>&1 &
  else printf 'console: %s\n' "$1"; fi
}

icm-up() {
  icm server start "$@" || return 1
  url="$(icm server status --url 2>/dev/null)"
  [ -n "$url" ] && _icm_open "$url"
}
icm-down() { icm server stop "$@"; }
icm-toggle() {
  icm server toggle "$@"
  url="$(icm server status --url 2>/dev/null)"
  [ -n "$url" ] && _icm_open "$url"
}
icm-console() {
  url="$(icm server status --url 2>/dev/null)"
  if [ -n "$url" ]; then _icm_open "$url"; else echo 'server is down; run icm-up first'; fi
}
icm-status() { icm server status; echo; icm status "$@"; }

icm-dry() {
  m="$(_icm_dry_marker)"; mkdir -p "$(dirname "$m")"
  case "${1:-toggle}" in
    on) : > "$m"; echo 'dry-run: ON (rounds use the deterministic agent)';;
    off) rm -f "$m"; echo 'dry-run: OFF (rounds use the real coding agent)';;
    *) if [ -f "$m" ]; then rm -f "$m"; echo 'dry-run: OFF'; else : > "$m"; echo 'dry-run: ON'; fi;;
  esac
}

icm-new() {
  obj="$*"
  if [ -z "$obj" ]; then printf 'objective> '; read -r obj; fi
  [ -z "$obj" ] && { echo 'no objective given'; return 1; }
  # shellcheck disable=SC2046
  icm new "$obj" --run $(_icm_dry_flag)
}
# shellcheck disable=SC2046
icm-run() { icm run "$@" $(_icm_dry_flag); }

_icm_round_menu() {
  rid="$1"
  printf 'action for %s  [s]tatus [d]iff [e]vents [a]pprove [c]ancel [r]etry [A]rtifacts> ' "$rid"
  read -r a
  case "$a" in
    d) icm diff "$rid";;
    e) icm events "$rid";;
    a) icm approve "$rid" --run $(_icm_dry_flag);;
    c) icm cancel "$rid";;
    r) icm retry "$rid" --run $(_icm_dry_flag);;
    A) icm artifacts "$rid";;
    *) icm status "$rid";;
  esac
}

icm-pick() {
  if command -v fzf >/dev/null 2>&1; then
    line="$(icm list | fzf --delimiter='\t' --with-nth=2,3,4 --prompt='round> ')" || return 0
  else
    icm list | nl -ba
    printf 'row #> '; read -r n
    line="$(icm list | sed -n "${n}p")"
  fi
  [ -z "$line" ] && return 0
  rid="${line%%$(printf '\t')*}"
  _icm_round_menu "$rid"
}
# --- end icm shell integration ---"""


def _add_round_argument(parser) -> None:
    parser.add_argument("round_id", nargs="?")


def _add_task_profile_arguments(parser) -> None:
    parser.add_argument("objective")
    parser.add_argument("--intent", choices=[item.value for item in TaskIntent], default="auto")
    parser.add_argument("--clarity", type=float, default=0.5)
    parser.add_argument("--uncertainty", type=float, default=0.5)
    parser.add_argument("--stakes", type=float, default=0.5)
    parser.add_argument("--reversibility", type=float, default=0.5)
    parser.add_argument("--production-change", action="store_true")
    parser.add_argument("--code-intensity", type=float, default=0.0)
    parser.add_argument("--research-intensity", type=float, default=0.0)
    parser.add_argument("--tool-intensity", type=float, default=0.0)
    parser.add_argument("--privacy-restricted", action="store_true")
    parser.add_argument("--latency-ms", type=int, default=10_000)
    parser.add_argument("--budget-usd", type=float)
    parser.add_argument("--require-capability", action="append", default=[])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="icm", description="ICM production harness")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="initialize an ICM workspace")
    init.add_argument("path", nargs="?", default=".")
    init.set_defaults(func=cmd_init)

    new = sub.add_parser("new", help="create and optionally run a round")
    _add_task_profile_arguments(new)
    new.add_argument("--run", action="store_true")
    new.add_argument(
        "--dry-run", action="store_true", help="exercise the full lifecycle without an AI agent"
    )
    new.add_argument("--json", action="store_true")
    new.set_defaults(func=cmd_new)

    run = sub.add_parser("run", help="run or resume a round")
    _add_round_argument(run)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--json", action="store_true")
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status", help="show round status")
    _add_round_argument(status)
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    list_command = sub.add_parser("list", help="list recent rounds")
    list_command.add_argument("--limit", type=int, default=100)
    list_command.add_argument("--json", action="store_true")
    list_command.set_defaults(func=cmd_list)

    events = sub.add_parser("events", help="show the append-only event trail")
    _add_round_argument(events)
    events.add_argument("--after", type=int, default=0)
    events.add_argument("--json", action="store_true")
    events.set_defaults(func=cmd_events)

    artifacts = sub.add_parser("artifacts", help="list or read round artifacts")
    _add_round_argument(artifacts)
    artifacts.add_argument("--artifact-id", type=int)
    artifacts.add_argument("--json", action="store_true")
    artifacts.set_defaults(func=cmd_artifacts)

    approve = sub.add_parser("approve", help="approve a waiting human gate")
    _add_round_argument(approve)
    approve.add_argument("--run", action="store_true")
    approve.set_defaults(func=cmd_approve)

    cancel = sub.add_parser("cancel", help="request cancellation")
    _add_round_argument(cancel)
    cancel.set_defaults(func=cmd_cancel)

    retry = sub.add_parser("retry", help="retry a failed, blocked, or cancelled round")
    _add_round_argument(retry)
    retry.add_argument("--run", action="store_true")
    retry.add_argument("--dry-run", action="store_true")
    retry.set_defaults(func=cmd_retry)

    diff = sub.add_parser("diff", help="show changes in an isolated round worktree")
    _add_round_argument(diff)
    diff.set_defaults(func=cmd_diff)

    promote = sub.add_parser("promote", help="merge a closed round worktree into the base branch")
    _add_round_argument(promote)
    promote.set_defaults(func=cmd_promote)

    doctor = sub.add_parser("doctor", help="check runtime prerequisites")
    doctor.set_defaults(func=cmd_doctor)

    serve_command = sub.add_parser("serve", help="start the local operator console (foreground)")
    serve_command.add_argument("--host")
    serve_command.add_argument("--port", type=int)
    serve_command.set_defaults(func=cmd_serve)

    server_command = sub.add_parser(
        "server", help="manage the operator console as a background service"
    )
    server_command.add_argument(
        "action", choices=["start", "stop", "restart", "status", "toggle"]
    )
    server_command.add_argument("--host")
    server_command.add_argument("--port", type=int)
    server_command.add_argument(
        "--url", action="store_true", help="with status: print only the URL"
    )
    server_command.add_argument("--json", action="store_true")
    server_command.set_defaults(func=cmd_server)

    shell_init = sub.add_parser(
        "shell-init", help="print shell functions to eval: eval \"$(icm shell-init)\""
    )
    shell_init.add_argument("shell", nargs="?", choices=["bash", "zsh"])
    shell_init.set_defaults(func=cmd_shell_init)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"icm: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
