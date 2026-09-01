import * as vscode from "vscode";
import { HarnessSettings } from "./config";

/**
 * Hosts the harness web console (served by `icm serve`) inside a webview panel,
 * reusing the existing operator UI for rich artifact/audit rendering. Native
 * VS Code views handle navigation, diffs, and gates; this panel is the deep
 * inspection surface.
 */
export class ConsolePanel {
  private static current: ConsolePanel | undefined;
  private readonly panel: vscode.WebviewPanel;
  private disposed = false;

  static show(settings: HarnessSettings): void {
    if (ConsolePanel.current) {
      ConsolePanel.current.panel.reveal(vscode.ViewColumn.Active);
      ConsolePanel.current.render(settings);
      return;
    }
    ConsolePanel.current = new ConsolePanel(settings);
  }

  private constructor(settings: HarnessSettings) {
    this.panel = vscode.window.createWebviewPanel(
      "icm.console",
      "ICM Operator Console",
      vscode.ViewColumn.Active,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        portMapping: [{ webviewPort: settings.port, extensionHostPort: settings.port }],
      },
    );
    this.panel.iconPath = new vscode.ThemeIcon("browser");
    this.panel.onDidDispose(() => {
      this.disposed = true;
      ConsolePanel.current = undefined;
    });
    this.render(settings);
  }

  private render(settings: HarnessSettings): void {
    if (this.disposed) {
      return;
    }
    const target = `http://localhost:${settings.port}/`;
    this.panel.webview.html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy"
    content="default-src 'none'; frame-src http://localhost:* http://127.0.0.1:*; style-src 'unsafe-inline';" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <style>
    html, body { margin: 0; padding: 0; height: 100%; }
    iframe { border: 0; width: 100%; height: 100vh; }
  </style>
</head>
<body>
  <iframe src="${target}" title="ICM Operator Console"></iframe>
</body>
</html>`;
  }
}
