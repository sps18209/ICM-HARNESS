# ICM Production Harness

A modular, filesystem-first AI work harness for VS Code and terminal-based coding agents.

The harness separates five concerns that are commonly collapsed into one agent loop:

1. cognitive mode selection;
2. context selection and token budgeting;
3. model/provider selection;
4. durable/concurrent execution;
5. independent evaluation and learning.

The custom control plane remains independent from any one model provider, coding agent, workflow engine,
MCP server, memory vendor, or observability backend.

## Quickstart (novice)

Three steps from a clone to a running console.

```bash
# 1. Install the `icm` command (uses pipx if present, else a local .venv)
./install.sh
#    …then add the printed line to your ~/.zshrc or ~/.bashrc, or let it do it.

# 2. Open a new terminal, go to your project, and initialize a workspace
cd ~/my-project
icm init

# 3. Bring up the operator console (starts the server + opens your browser)
icm-up
```

Now you have shell helpers (from `eval "$(icm shell-init)"`):

| Command | What it does |
| --- | --- |
| `icm-up` / `icm-down` / `icm-toggle` | start / stop / flip the operator console server |
| `icm-console` | open the console URL in your browser |
| `icm-new "objective"` | create and run a round (prompts if no objective) |
| `icm-dry [on\|off]` | toggle dry-run mode (safe deterministic agent vs. the real coding agent) |
| `icm-pick` | pick a round (via `fzf` if installed) and act on it — status / diff / approve / cancel / retry / artifacts |
| `icm-status` | server + current-round status |

New here? Start in dry-run so nothing calls a real model:

```bash
icm-dry on
icm-new "add a hello-world endpoint"
icm-pick          # inspect it: status, diff, artifacts
```

Run `icm doctor` any time to check prerequisites (Python, git, agent binary, `fzf`, server state).
`icm --help` lists the full command set; the shell helpers wrap those.

Prefer a GUI? See [`extension/`](extension/README.md) for the VS Code extension, which drives the same
server.

## Ephemeral single-session use (no global install)

Hand an agent like Claude Code the repository — cloned or as a downloaded, unzipped
zip — and stand the harness up for **that session only**, with zero global footprint
(no `pipx`, no shell-rc edits, no `~/.claude` changes):

```bash
eval "$(bash scripts/session-init.sh)"   # ephemeral venv + workspace; activates `icm`
icm doctor                                # verify
```

`scripts/session-init.sh` builds a session-scoped virtualenv under a temp directory,
installs a snapshot of the harness into it, and initializes an ICM workspace in the
current project. Human-readable logs go to stderr; the only line on stdout is the
`export PATH=…` activation, so the `eval` form above just works (run it without
`eval` to read the logs and copy the printed line yourself). When you are done,
everything is removed by deleting one directory — the script prints the exact
`rm -rf` line.

Useful flags (`--help` lists them all): `--project DIR` (workspace target),
`--home DIR` (where the venv lives; reused if present), `--with-mcp` (also write a
removable project-local `.mcp.json` for the `icm-harness` MCP server — restart the
session to load it), `--no-init`, `--dev`, `--python BIN`. `make session-init` runs
it with defaults.

## Use ICM from an agent

The repository includes a stdio MCP server exposing round operations to VS Code
agents. Install the project into the Python environment used by VS Code:

```bash
pip install -e .
icm init .
```

Open this repository as a VS Code workspace. The checked-in
[`.vscode/mcp.json`](.vscode/mcp.json) registers `icm-harness` automatically.
The server runs in the workspace directory and exposes tools for creating,
running, inspecting, approving, retrying, cancelling, and promoting rounds,
as well as reading events, artifacts, and diffs.

The MCP server uses the same `HarnessApplication` as the CLI and extension. It
does not replace `icm serve`; both can operate on the same initialized
workspace.

## Coding agent providers

A round's mutating work is carried out by a coding-agent subprocess, chosen by
`[agent]` in `.harness/config.toml` (or the `ICM_AGENT_*` env overrides). Three
providers ship:

- `dry-run` — a deterministic stand-in; no model is called. The default for
  `icm-dry on`, and what every example above uses until you opt out.
- `codex-cli` — OpenAI's `codex exec` (the shipped default). Needs the `codex`
  binary and its auth.
- `claude-cli` — Anthropic's `claude` CLI in headless mode
  (`claude -p --output-format json`). Needs the `claude` binary on `PATH`; the
  adapter forwards the `ANTHROPIC_*` / `CLAUDE_CODE_*` auth env the CLI uses.

The provider only changes how a stage is executed — every provider returns the
same structured `StageResult` against the same contract, and the harness grades,
gates, and isolates the work identically. Switch to Claude for a workspace:

```bash
# one-off, via env:
ICM_AGENT_PROVIDER=claude-cli ICM_AGENT_EXECUTABLE=claude icm new "…" --run

# or persist it in .harness/config.toml:
#   [agent]
#   provider = "claude-cli"
#   executable = "claude"
#   [models.default]
#   provider = "claude-cli"   # the model router only offers models whose
#   family = "claude"         # provider matches [agent].provider
```

A non-mutating stage runs the agent with its write tools denied
(`--disallowed-tools`); a mutating stage runs under `--permission-mode
acceptEdits` so it is non-interactive without granting a blanket
permission bypass. `icm doctor` reports the configured agent binary either way.

## Core modes

- `discovery`: frame -> explore -> research -> adversarial -> synthesis -> validate
- `build`: planner -> writer -> tester -> close
- `decision`: frame -> evidence -> options -> adversarial -> decide -> validate -> close
- `review`: ingest -> reconstruct -> inspect -> adversarial -> findings
- `quick`: execute -> verify -> close

Modes compose. A technically uncertain build is represented as `discovery -> build`, not as a new
monolithic mode.

## Non-negotiable invariants

- Planner does not implement.
- Writer does not redefine.
- Tester does not repair.
- Durable project facts are distinct from round-specific artifacts.
- Context is pulled in tiers; "load the repository" is not a fallback.
- Mutating work is isolated in Git worktrees.
- Every running stage has a lease and expiry.
- Retries are bounded and observable.
- Concurrency is keyed to the resource being protected.
- Token and dollar budgets are explicit inputs to routing.
- External integrations are adapters, not sources of domain logic.
