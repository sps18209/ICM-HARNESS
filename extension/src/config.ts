import * as vscode from "vscode";

export interface HarnessSettings {
  host: string;
  port: number;
  token: string;
  python: string;
  autoStartServer: boolean;
  dryRun: boolean;
  refreshIntervalMs: number;
}

export function readSettings(): HarnessSettings {
  const cfg = vscode.workspace.getConfiguration("icm");
  return {
    host: cfg.get<string>("host", "127.0.0.1"),
    port: cfg.get<number>("port", 8765),
    token: cfg.get<string>("token", "").trim(),
    python: cfg.get<string>("python", "python3"),
    autoStartServer: cfg.get<boolean>("autoStartServer", true),
    dryRun: cfg.get<boolean>("dryRun", false),
    refreshIntervalMs: Math.max(500, cfg.get<number>("refreshIntervalMs", 1500)),
  };
}

export function baseUrl(settings: HarnessSettings): string {
  return `http://${settings.host}:${settings.port}`;
}
