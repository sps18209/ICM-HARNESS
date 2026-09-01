#!/usr/bin/env bash
# One-shot installer for the ICM production harness.
#
#   ./install.sh
#
# Puts the `icm` command on your PATH (via pipx if available, otherwise a local
# virtualenv), then prints the one line to add to your shell so you get the
# icm-up / icm-toggle / icm-new / icm-pick helpers.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

say() { printf '\033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*" >&2; }
die() { printf '\033[31merror: %s\033[0m\n' "$*" >&2; exit 1; }

# 1. Find a Python >= 3.11.
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)' 2>/dev/null; then
      PYTHON="$candidate"
      break
    fi
  fi
done
[ -n "$PYTHON" ] || die "Python 3.11+ is required but was not found. Install it and re-run."
say "Using $($PYTHON --version) ($(command -v "$PYTHON"))"

# 2. Install so `icm` is on PATH. Prefer pipx; fall back to a project venv.
ICM_BIN=""
INSTALL_MODE=""
if command -v pipx >/dev/null 2>&1; then
  say "Installing with pipx (isolated, global command)…"
  pipx install --force "$REPO_DIR" >/dev/null
  pipx ensurepath >/dev/null 2>&1 || true
  ICM_BIN="icm"
  INSTALL_MODE="pipx"
else
  warn "pipx not found; falling back to a local virtualenv at .venv"
  "$PYTHON" -m venv "$REPO_DIR/.venv"
  "$REPO_DIR/.venv/bin/python" -m pip install -q --upgrade pip
  "$REPO_DIR/.venv/bin/python" -m pip install -q "$REPO_DIR"
  ICM_BIN="$REPO_DIR/.venv/bin/icm"
  INSTALL_MODE="venv"
fi

# 3. Verify the command runs.
"$ICM_BIN" shell-init bash >/dev/null || die "installation produced a non-working icm command"
say "icm installed OK."

# 4. Print (and optionally install) shell integration.
SHELL_NAME="$(basename "${SHELL:-bash}")"
case "$SHELL_NAME" in
  zsh) RC="$HOME/.zshrc" ;;
  bash) RC="$HOME/.bashrc" ;;
  *) SHELL_NAME="bash"; RC="$HOME/.bashrc" ;;
esac

EVAL_LINE="eval \"\$(${ICM_BIN} shell-init ${SHELL_NAME})\""
PATH_LINE=""
if [ "$INSTALL_MODE" = "venv" ]; then
  PATH_LINE="export PATH=\"$REPO_DIR/.venv/bin:\$PATH\""
fi

echo
say "Add this to $RC:"
[ -n "$PATH_LINE" ] && printf '  %s\n' "$PATH_LINE"
printf '  %s\n' "$EVAL_LINE"
echo

if [ -t 0 ]; then
  printf 'Append it to %s now? [y/N] ' "$RC"
  read -r reply
  if [ "$reply" = "y" ] || [ "$reply" = "Y" ]; then
    {
      echo ""
      echo "# ICM production harness"
      [ -n "$PATH_LINE" ] && echo "$PATH_LINE"
      echo "$EVAL_LINE"
    } >> "$RC"
    say "Done. Open a new terminal (or: source $RC), then run:  icm init  &&  icm-up"
  else
    say "Skipped. Add the line yourself, then run:  icm init  &&  icm-up"
  fi
else
  say "Then open a new terminal and run:  icm init  &&  icm-up"
fi
