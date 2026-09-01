import * as childProcess from "child_process";
import * as vscode from "vscode";
import { HarnessClient } from "./api";
import { HarnessSettings } from "./config";

/**
 * Owns the lifecycle of a locally launched `icm serve` process. The extension
 * is a client of the operator API; this only starts a server when one is not
 * already reachable, and it always talks to the same application service the
 * CLI and web console use.
 */
export class ServerManager {
  private child: childProcess.ChildProcess | undefined;
  private readonly output: vscode.OutputChannel;

  constructor(
    private readonly client: HarnessClient,
    output: vscode.OutputChannel,
  ) {
    this.output = output;
  }

  get isManaged(): boolean {
    return this.child !== undefined && this.child.exitCode === null;
  }

  /** Ensure a server is reachable, launching one if necessary. */
  async ensure(settings: HarnessSettings, cwd: string | undefined): Promise<boolean> {
    if (await this.client.health()) {
      return true;
    }
    if (!settings.autoStartServer) {
      return false;
    }
    return this.start(settings, cwd);
  }

  async start(settings: HarnessSettings, cwd: string | undefined): Promise<boolean> {
    if (this.isManaged) {
      return true;
    }
    if (await this.client.health()) {
      return true;
    }
    const env = { ...process.env };
    if (settings.token) {
      env.ICM_WEB_TOKEN = settings.token;
    }
    const args = [
      "-m",
      "icm_harness",
      "serve",
      "--host",
      settings.host,
      "--port",
      String(settings.port),
    ];
    this.output.appendLine(`starting: ${settings.python} ${args.join(" ")}`);
    this.child = childProcess.spawn(settings.python, args, {
      cwd,
      env,
    });
    this.child.stdout?.on("data", (d) => this.output.append(d.toString()));
    this.child.stderr?.on("data", (d) => this.output.append(d.toString()));
    this.child.on("exit", (code) => {
      this.output.appendLine(`server exited with code ${code}`);
      this.child = undefined;
    });

    return this.waitForHealth(20);
  }

  stop(): void {
    if (this.child) {
      this.output.appendLine("stopping managed server");
      this.child.kill();
      this.child = undefined;
    }
  }

  dispose(): void {
    this.stop();
  }

  private async waitForHealth(attempts: number): Promise<boolean> {
    for (let i = 0; i < attempts; i++) {
      if (await this.client.health()) {
        return true;
      }
      await delay(250);
    }
    return false;
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
