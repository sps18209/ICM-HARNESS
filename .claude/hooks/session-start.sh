#!/bin/bash
# Auto-install the ICM harness so `icm` (CLI + MCP server) and the /icm skill are
# ready the moment a Claude Code on the web session opens this repo. Sharing the
# GitHub repo is then enough — no manual setup.
#
# Web-only, idempotent, non-interactive, and tolerant of an offline sandbox.
set -euo pipefail

# Only run in the remote (Claude Code on the web) environment.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# Already installed (e.g. a resumed / cached container)? Nothing to do.
if command -v icm >/dev/null 2>&1; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

# Editable install. The only runtime dep is anyio; the dev extra adds pytest+ruff
# so tests and linters work in-session. Failure (e.g. no network) is non-fatal —
# the /icm skill still self-drives.
if python3 -m pip install -e ".[dev]" >/dev/null 2>&1; then
  echo "icm: harness installed — the icm CLI and icm-mcp server are ready." >&2
else
  echo "icm: pip install failed (offline sandbox?); run 'pip install -e .' manually to enable the CLI." >&2
fi
