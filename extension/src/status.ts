import * as vscode from "vscode";
import { HarnessClient } from "./api";
import { Round } from "./types";

const ACTIVE_STATUSES = new Set(["running", "waiting_approval", "active"]);

/**
 * Polls the server on an interval to drive the status bar item, fire the tree
 * refresh, and raise a notification whenever a round is waiting on a human gate.
 */
export class StatusWatcher {
  private readonly item: vscode.StatusBarItem;
  private timer: NodeJS.Timeout | undefined;
  private notifiedGates = new Set<string>();

  constructor(
    private readonly client: HarnessClient,
    private readonly onRounds: (rounds: Round[], reachable: boolean) => void,
  ) {
    this.item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
    this.item.command = "icm.openConsole";
    this.item.text = "$(sync~spin) ICM";
    this.item.tooltip = "ICM Harness — click to open the operator console";
  }

  start(intervalMs: number): void {
    this.stop();
    void this.tick();
    this.timer = setInterval(() => void this.tick(), intervalMs);
  }

  stop(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = undefined;
    }
  }

  dispose(): void {
    this.stop();
    this.item.dispose();
  }

  private async tick(): Promise<void> {
    let rounds: Round[] = [];
    let reachable = true;
    try {
      rounds = await this.client.listRounds();
    } catch {
      reachable = false;
    }

    this.onRounds(rounds, reachable);
    this.render(rounds, reachable);
    if (reachable) {
      this.checkGates(rounds);
    }
  }

  private render(rounds: Round[], reachable: boolean): void {
    if (!reachable) {
      this.item.text = "$(debug-disconnect) ICM offline";
      this.item.tooltip = "ICM server not reachable — run ICM: Start Server";
      this.item.show();
      return;
    }
    const waiting = rounds.filter((r) => r.status === "waiting_approval");
    const active = rounds.filter((r) => ACTIVE_STATUSES.has(r.status));
    if (waiting.length > 0) {
      this.item.text = `$(person) ICM gate (${waiting.length})`;
      this.item.tooltip = "Round(s) awaiting human approval";
    } else if (active.length > 0) {
      const running = active.find((r) => r.status === "running") ?? active[0];
      const stage = running.current_stage ? ` · ${running.current_stage}` : "";
      this.item.text = `$(sync~spin) ICM${stage}`;
      this.item.tooltip = `${active.length} active round(s)`;
    } else {
      this.item.text = "$(circle-outline) ICM";
      this.item.tooltip = "ICM Harness — no active rounds";
    }
    this.item.show();
  }

  private checkGates(rounds: Round[]): void {
    const currentKeys = new Set<string>();
    for (const round of rounds) {
      if (round.status !== "waiting_approval") {
        continue;
      }
      const key = `${round.round_id}:${round.active_gate ?? ""}`;
      currentKeys.add(key);
      if (this.notifiedGates.has(key)) {
        continue;
      }
      this.notifiedGates.add(key);
      this.promptGate(round);
    }
    // Forget gates that are no longer waiting so re-entry re-notifies.
    for (const key of [...this.notifiedGates]) {
      if (!currentKeys.has(key)) {
        this.notifiedGates.delete(key);
      }
    }
  }

  private promptGate(round: Round): void {
    const gate = round.active_gate ?? "gate";
    void vscode.window
      .showInformationMessage(
        `Approval required before "${gate}" — ${round.objective}`,
        "Approve",
        "Cancel Round",
        "Show Events",
      )
      .then((choice) => {
        if (choice === "Approve") {
          void vscode.commands.executeCommand("icm.approveRound", { round });
        } else if (choice === "Cancel Round") {
          void vscode.commands.executeCommand("icm.cancelRound", { round });
        } else if (choice === "Show Events") {
          void vscode.commands.executeCommand("icm.showEvents", { round });
        }
      });
  }
}
