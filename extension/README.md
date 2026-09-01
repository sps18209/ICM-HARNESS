# ICM Production Harness — VS Code Extension

Operate the ICM harness from inside VS Code. The extension is a thin client of
the same `HarnessApplication` service the CLI and web console use — it talks to
the local operator HTTP API served by `icm serve`.

## What it gives you

- **Rounds view** (activity bar): rounds → stages → artifacts, with live,
  status-driven icons (running, awaiting approval, failed, closed).
- **Command palette + context menus**: new round, run/resume, approve gate,
  cancel, retry, promote.
- **Native worktree diff**: `ICM: Show Worktree Diff` opens the isolated round
  worktree diff as a read-only `diff` document.
- **Artifacts & event trail**: open any artifact or the append-only audit trail
  as a read-only editor.
- **Status bar**: shows the active round/stage or a pending human gate.
- **Human-gate notifications**: when a round waits for approval, you get a toast
  with Approve / Cancel / Show Events.
- **Operator console**: `ICM: Open Operator Console` embeds the existing web
  console in a webview for rich inspection.

## How it connects

On activation the extension checks `http://<host>:<port>/api/health`. If nothing
answers and `icm.autoStartServer` is on, it launches:

```
<icm.python> -m icm_harness serve --host <host> --port <port>
```

from the first workspace folder. If `icm.token` is set it is injected as
`ICM_WEB_TOKEN` (required only when binding outside loopback).

## Settings

| Setting | Default | Purpose |
| --- | --- | --- |
| `icm.host` | `127.0.0.1` | Operator server host |
| `icm.port` | `8765` | Operator server port |
| `icm.token` | `""` | Bearer token; injected into a managed server |
| `icm.python` | `python3` | Interpreter for `-m icm_harness serve` |
| `icm.autoStartServer` | `true` | Auto-launch the server if unreachable |
| `icm.dryRun` | `false` | Run rounds with the deterministic dry-run agent |
| `icm.refreshIntervalMs` | `1500` | Poll cadence for tree/status/gates |

## Develop

```
cd extension
npm install
npm run compile      # or: npm run watch
```

Then press F5 in VS Code (Extension Development Host). Requires the harness to be
importable by `icm.python` (e.g. `pip install -e .` in the repo root).
