import * as vscode from "vscode";
import { HarnessClient } from "./api";
import { ConsolePanel } from "./console";
import { HarnessSettings, readSettings } from "./config";
import { HarnessDocumentProvider, openVirtualDocument } from "./docs";
import { languageFor } from "./logic";
import { ServerManager } from "./server";
import { Round } from "./types";

interface Deps {
  client: HarnessClient;
  docs: HarnessDocumentProvider;
  server: ServerManager;
  output: vscode.OutputChannel;
  refresh: () => void;
  settings: () => HarnessSettings;
}

// Must match TaskIntent in src/icm_harness/kernel/contracts.py.
const INTENTS = ["auto", "build", "investigate", "decide", "review", "quick"];

export function registerCommands(context: vscode.ExtensionContext, deps: Deps): void {
  const reg = (id: string, fn: (...args: unknown[]) => unknown) =>
    context.subscriptions.push(vscode.commands.registerCommand(id, fn));

  reg("icm.refresh", () => deps.refresh());
  reg("icm.newRound", () => newRound(deps));
  reg("icm.runRound", (arg) => run(deps, () => resolveId(deps, arg), "run"));
  reg("icm.approveRound", (arg) => run(deps, () => resolveId(deps, arg), "approve"));
  reg("icm.cancelRound", (arg) => run(deps, () => resolveId(deps, arg), "cancel"));
  reg("icm.retryRound", (arg) => run(deps, () => resolveId(deps, arg), "retry"));
  reg("icm.promoteRound", (arg) => run(deps, () => resolveId(deps, arg), "promote"));
  reg("icm.showDiff", (arg) => showDiff(deps, arg));
  reg("icm.showEvents", (arg) => showEvents(deps, arg));
  reg("icm.openArtifact", (arg) => openArtifact(deps, arg));
  reg("icm.openConsole", () => ConsolePanel.show(deps.settings()));
  reg("icm.startServer", () => startServer(deps));
  reg("icm.stopServer", () => {
    deps.server.stop();
    deps.refresh();
  });
}

function extractRound(arg: unknown): Round | undefined {
  if (arg && typeof arg === "object") {
    const obj = arg as { round?: Round; kind?: string };
    if (obj.round) {
      return obj.round;
    }
    if (obj.kind === "round" && "round" in obj) {
      return (obj as { round: Round }).round;
    }
  }
  return undefined;
}

async function resolveId(deps: Deps, arg: unknown): Promise<string | undefined> {
  const round = extractRound(arg);
  if (round) {
    return round.round_id;
  }
  if (typeof arg === "string") {
    return arg;
  }
  return pickRound(deps);
}

async function pickRound(deps: Deps): Promise<string | undefined> {
  let rounds: Round[];
  try {
    rounds = await deps.client.listRounds();
  } catch (err) {
    vscode.window.showErrorMessage(`ICM: ${(err as Error).message}`);
    return undefined;
  }
  if (rounds.length === 0) {
    vscode.window.showInformationMessage("ICM: no rounds yet");
    return undefined;
  }
  const pick = await vscode.window.showQuickPick(
    rounds.map((r) => ({
      label: r.objective,
      description: `${r.status}${r.current_stage ? " · " + r.current_stage : ""}`,
      detail: r.round_id,
    })),
    { placeHolder: "Select a round" },
  );
  return pick?.detail;
}

async function run(
  deps: Deps,
  idResolver: () => Promise<string | undefined>,
  action: "run" | "approve" | "cancel" | "retry" | "promote",
): Promise<void> {
  const id = await idResolver();
  if (!id) {
    return;
  }
  const dryRun = deps.settings().dryRun;
  try {
    switch (action) {
      case "run":
        await deps.client.runRound(id, dryRun);
        break;
      case "approve":
        await deps.client.approveRound(id, true, dryRun);
        break;
      case "cancel":
        await deps.client.cancelRound(id);
        break;
      case "retry":
        await deps.client.retryRound(id, true, dryRun);
        break;
      case "promote":
        await deps.client.promoteRound(id);
        vscode.window.showInformationMessage(`ICM: promoted ${id}`);
        break;
    }
  } catch (err) {
    vscode.window.showErrorMessage(`ICM ${action} failed: ${(err as Error).message}`);
  }
  deps.refresh();
}

async function newRound(deps: Deps): Promise<void> {
  const objective = await vscode.window.showInputBox({
    prompt: "Round objective",
    placeHolder: "e.g. Add retry backoff to the ingestion worker",
    validateInput: (v) => (v.trim() ? undefined : "objective is required"),
  });
  if (!objective) {
    return;
  }
  const intent = await vscode.window.showQuickPick(INTENTS, {
    placeHolder: "Cognitive mode (auto lets the router decide)",
  });
  if (!intent) {
    return;
  }
  const runNow = await vscode.window.showQuickPick(["Create and run", "Create only"], {
    placeHolder: "Start the round now?",
  });
  if (!runNow) {
    return;
  }
  try {
    const round = await deps.client.createRound({
      objective: objective.trim(),
      intent,
      run: runNow === "Create and run",
      dry_run: deps.settings().dryRun,
    });
    vscode.window.showInformationMessage(
      `ICM: created ${round.round_id} (${round.route.join(" → ") || "routed"})`,
    );
  } catch (err) {
    vscode.window.showErrorMessage(`ICM new round failed: ${(err as Error).message}`);
  }
  deps.refresh();
}

async function showDiff(deps: Deps, arg: unknown): Promise<void> {
  const id = await resolveId(deps, arg);
  if (!id) {
    return;
  }
  try {
    const content = await deps.client.diff(id);
    const uri = deps.docs.set(`diff/${id}.diff`, content || "(no changes in worktree)\n");
    await openVirtualDocument(uri, "diff");
  } catch (err) {
    vscode.window.showErrorMessage(`ICM diff failed: ${(err as Error).message}`);
  }
}

async function showEvents(deps: Deps, arg: unknown): Promise<void> {
  const id = await resolveId(deps, arg);
  if (!id) {
    return;
  }
  try {
    const events = await deps.client.events(id);
    const lines = events.map((e) => {
      const stage = e.stage_ref ? ` [${e.stage_ref}]` : "";
      const payload = Object.keys(e.payload).length ? ` ${JSON.stringify(e.payload)}` : "";
      return `${e.created_at}  #${e.id}${stage} ${e.kind}${payload}`;
    });
    const uri = deps.docs.set(`events/${id}.log`, lines.join("\n") + "\n");
    await openVirtualDocument(uri, "log");
  } catch (err) {
    vscode.window.showErrorMessage(`ICM events failed: ${(err as Error).message}`);
  }
}

async function openArtifact(deps: Deps, arg: unknown): Promise<void> {
  const artifactId = typeof arg === "number" ? arg : Number(arg);
  if (!Number.isFinite(artifactId)) {
    return;
  }
  try {
    const artifact = await deps.client.artifact(artifactId);
    const uri = deps.docs.set(`artifacts/${artifactId}/${artifact.name}`, artifact.content);
    await openVirtualDocument(uri, languageFor(artifact.name, artifact.media_type));
  } catch (err) {
    vscode.window.showErrorMessage(`ICM artifact failed: ${(err as Error).message}`);
  }
}

async function startServer(deps: Deps): Promise<void> {
  const cwd = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  const ok = await deps.server.start(readSettings(), cwd);
  if (ok) {
    vscode.window.showInformationMessage("ICM: server is up");
  } else {
    vscode.window.showErrorMessage(
      "ICM: server did not become healthy — check the ICM Harness output channel",
    );
    deps.output.show(true);
  }
  deps.refresh();
}
