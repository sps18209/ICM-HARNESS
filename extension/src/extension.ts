import * as vscode from "vscode";
import { HarnessClient } from "./api";
import { registerCommands } from "./commands";
import { readSettings } from "./config";
import { HarnessDocumentProvider, SCHEME } from "./docs";
import { ServerManager } from "./server";
import { StatusWatcher } from "./status";
import { RoundsTreeProvider } from "./tree";

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  const output = vscode.window.createOutputChannel("ICM Harness");
  const client = new HarnessClient(readSettings());
  const docs = new HarnessDocumentProvider();
  const server = new ServerManager(client, output);
  const tree = new RoundsTreeProvider(client);

  context.subscriptions.push(
    output,
    server,
    vscode.workspace.registerTextDocumentContentProvider(SCHEME, docs),
    vscode.window.registerTreeDataProvider("icm.rounds", tree),
  );

  const watcher = new StatusWatcher(client, (rounds, reachable) => {
    tree.setReachable(reachable);
    tree.refresh();
    void rounds; // rounds are re-fetched by the tree; the watcher owns cadence
  });
  context.subscriptions.push(watcher);

  const refresh = () => tree.refresh();

  registerCommands(context, {
    client,
    docs,
    server,
    output,
    refresh,
    settings: readSettings,
  });

  // React to configuration changes (host/port/token/interval).
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("icm")) {
        const next = readSettings();
        client.update(next);
        watcher.start(next.refreshIntervalMs);
      }
    }),
  );

  const settings = readSettings();
  const cwd = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  const reachable = await server.ensure(settings, cwd);
  tree.setReachable(reachable);
  watcher.start(settings.refreshIntervalMs);
  tree.refresh();
}

export function deactivate(): void {
  /* subscriptions dispose the server and watcher */
}
