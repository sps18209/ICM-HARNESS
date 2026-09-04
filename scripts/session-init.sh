#!/usr/bin/env bash
# session-init.sh — stand up the ICM harness for THIS session only.
#
# Creates an ephemeral, session-scoped virtualenv, installs the harness into it,
# and (by default) initializes an ICM workspace in your project. Nothing global
# is touched: no pipx, no ~/.bashrc / ~/.zshrc edits, no ~/.claude changes. When
# the session ends, delete one directory and every trace is gone.
#
# Typical use (hand Claude Code the repo — cloned or unzipped — then):
#
#     eval "$(bash scripts/session-init.sh)"      # activates `icm` in this shell
#     icm doctor                                  # verify
#
# Human-readable logs go to stderr; the single line printed to stdout is the
# `export PATH=...` activation, so the `eval` form above just works. Run it
# without `eval` to read the logs and copy the printed activation line yourself.
#
# Flags:
#   --project DIR   Project to initialize a workspace in (default: current dir).
#   --home DIR      Where the ephemeral venv lives (default: $ICM_SESSION_HOME
#                   or a fresh mktemp dir). Reused if it already holds a venv.
#   --repo DIR      Harness source tree (default: this script's repo root).
#   --python BIN    Python interpreter to build the venv with (default: python3).
#   --with-mcp      Also write a removable project-local .mcp.json registering the
#                   icm-harness MCP server. NOTE: Claude Code loads MCP servers at
#                   startup, so restart the session in the project to pick it up.
#   --dev           Include dev extras (pytest, ruff) in the venv.
#   --no-init       Do not create/refresh a workspace; just build the venv.
#   -h, --help      Show this help.
set -euo pipefail

log()  { printf '%s\n' "$*" >&2; }
die()  { printf 'session-init: %s\n' "$*" >&2; exit 1; }

PROJECT="$PWD"
HOME_DIR="${ICM_SESSION_HOME:-}"
REPO_ROOT=""
PYTHON_BIN="python3"
WITH_MCP=0
DEV=0
DO_INIT=1

while [ $# -gt 0 ]; do
  case "$1" in
    --project) PROJECT="${2:?--project needs a path}"; shift 2 ;;
    --home)    HOME_DIR="${2:?--home needs a path}"; shift 2 ;;
    --repo)    REPO_ROOT="${2:?--repo needs a path}"; shift 2 ;;
    --python)  PYTHON_BIN="${2:?--python needs a binary}"; shift 2 ;;
    --with-mcp) WITH_MCP=1; shift ;;
    --dev)     DEV=1; shift ;;
    --no-init) DO_INIT=0; shift ;;
    -h|--help)
      sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//' >&2
      exit 0 ;;
    *) die "unknown argument: $1 (try --help)" ;;
  esac
done

# --- resolve the harness source tree --------------------------------------
if [ -z "$REPO_ROOT" ]; then
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  REPO_ROOT="$(cd "$script_dir/.." && pwd)"
fi
[ -f "$REPO_ROOT/pyproject.toml" ] || die "no pyproject.toml under --repo '$REPO_ROOT'; point --repo at the harness source tree"
grep -q 'icm-production-harness' "$REPO_ROOT/pyproject.toml" 2>/dev/null \
  || die "'$REPO_ROOT' does not look like the ICM harness (pyproject name mismatch)"

# --- preflight: a usable Python ------------------------------------------
command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "'$PYTHON_BIN' not found; install Python >= 3.11 or pass --python"
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)'; then
  have="$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo '?')"
  die "Python >= 3.11 required, found $have; pass a newer interpreter with --python"
fi
"$PYTHON_BIN" -c 'import venv' >/dev/null 2>&1 || die "the 'venv' module is unavailable for $PYTHON_BIN (on Debian/Ubuntu: apt install python3-venv)"

# --- session-scoped home + venv ------------------------------------------
if [ -z "$HOME_DIR" ]; then
  HOME_DIR="$(mktemp -d "${TMPDIR:-/tmp}/icm-session.XXXXXX")"
fi
mkdir -p "$HOME_DIR"
HOME_DIR="$(cd "$HOME_DIR" && pwd)"
VENV="$HOME_DIR/venv"

if [ -x "$VENV/bin/icm" ]; then
  log "• reusing existing session venv at $VENV"
else
  log "• creating ephemeral venv at $VENV"
  "$PYTHON_BIN" -m venv "$VENV"
  # Best-effort pip refresh; tolerate an offline or already-current pip.
  "$VENV/bin/python" -m pip install --quiet --upgrade pip >&2 2>/dev/null || \
    log "  (pip upgrade skipped — continuing with the bundled pip)"
  target="$REPO_ROOT"; [ "$DEV" -eq 1 ] && target="$REPO_ROOT[dev]"
  log "• installing the harness into the session venv (this is a snapshot copy, not a link)"
  if ! "$VENV/bin/python" -m pip install --quiet "$target" >&2; then
    die "pip could not install the harness. If this session has no network access, that is the likely cause (the only runtime dependency is 'anyio')."
  fi
fi

command -v "$VENV/bin/icm" >/dev/null 2>&1 || die "install finished but 'icm' is missing from the venv — please report this"
"$VENV/bin/icm" --help >/dev/null 2>&1 || die "'icm' installed but does not run cleanly"
log "• icm is ready: $VENV/bin/icm"

# --- workspace init (idempotent, non-destructive) ------------------------
if [ "$DO_INIT" -eq 1 ]; then
  PROJECT="$(cd "$PROJECT" && pwd)"
  if [ -f "$PROJECT/.harness/config.toml" ]; then
    log "• workspace already initialized in $PROJECT (leaving it untouched)"
  else
    log "• initializing an ICM workspace in $PROJECT"
    "$VENV/bin/icm" init "$PROJECT" >&2
  fi
fi

# --- optional, opt-in MCP registration -----------------------------------
if [ "$WITH_MCP" -eq 1 ]; then
  PROJECT="$(cd "$PROJECT" && pwd)"
  mcp_file="$PROJECT/.mcp.json"
  server_cmd="$VENV/bin/icm-mcp"
  if [ -e "$mcp_file" ]; then
    log "• $mcp_file already exists — not overwriting. Add this server yourself:"
    log "    icm-harness -> command: $server_cmd  (cwd: $PROJECT)"
  else
    ICM_MCP_CMD="$server_cmd" ICM_MCP_CWD="$PROJECT" "$VENV/bin/python" - "$mcp_file" <<'PY' >&2
import json, os, sys
path = sys.argv[1]
doc = {"mcpServers": {"icm-harness": {
    "command": os.environ["ICM_MCP_CMD"], "args": [], "cwd": os.environ["ICM_MCP_CWD"],
}}}
with open(path, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, indent=2)
    fh.write("\n")
PY
    log "• wrote $mcp_file (icm-harness MCP server)"
    log "  ↳ RESTART Claude Code in this project to load the ICM tools; delete $mcp_file to undo."
  fi
fi

# --- summary + teardown notes (stderr), activation line (stdout) ---------
log ""
log "ICM harness is live for this session."
log "  session home : $HOME_DIR"
log "  project      : $PROJECT"
log "  activate now : eval \"\$(bash ${BASH_SOURCE[0]} --home '$HOME_DIR')\""
log "  or by hand   : export PATH=\"$VENV/bin:\$PATH\""
log "  tear down    : rm -rf '$HOME_DIR'$( [ "$WITH_MCP" -eq 1 ] && printf '   (and rm %s/.mcp.json)' "$PROJECT" )"
log ""

# The one and only stdout line: safe to `eval`.
printf 'export PATH=%q:$PATH\n' "$VENV/bin"
