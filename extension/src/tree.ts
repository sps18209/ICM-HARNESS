import * as vscode from "vscode";
import { HarnessClient } from "./api";
import { stageState, statusIcon, truncateObjective } from "./logic";
import { ArtifactRecord, Round } from "./types";

type Node = RoundNode | StageNode | ArtifactsGroupNode | ArtifactNode | MessageNode;

interface RoundNode {
  kind: "round";
  round: Round;
}
interface StageNode {
  kind: "stage";
  round: Round;
  stageRef: string;
  index: number;
}
interface ArtifactsGroupNode {
  kind: "artifacts";
  round: Round;
}
interface ArtifactNode {
  kind: "artifact";
  artifact: ArtifactRecord;
}
interface MessageNode {
  kind: "message";
  text: string;
}

export class RoundsTreeProvider implements vscode.TreeDataProvider<Node> {
  private readonly _onDidChange = new vscode.EventEmitter<Node | undefined | void>();
  readonly onDidChangeTreeData = this._onDidChange.event;

  private rounds: Round[] = [];
  private reachable = false;

  constructor(private readonly client: HarnessClient) {}

  setReachable(reachable: boolean): void {
    this.reachable = reachable;
  }

  refresh(): void {
    this._onDidChange.fire();
  }

  getTreeItem(node: Node): vscode.TreeItem {
    switch (node.kind) {
      case "round":
        return this.roundItem(node.round);
      case "stage":
        return this.stageItem(node);
      case "artifacts": {
        const item = new vscode.TreeItem(
          "Artifacts",
          vscode.TreeItemCollapsibleState.Collapsed,
        );
        item.iconPath = new vscode.ThemeIcon("files");
        item.contextValue = "artifacts";
        return item;
      }
      case "artifact":
        return this.artifactItem(node.artifact);
      case "message": {
        const item = new vscode.TreeItem(node.text, vscode.TreeItemCollapsibleState.None);
        item.iconPath = new vscode.ThemeIcon("info");
        return item;
      }
    }
  }

  async getChildren(node?: Node): Promise<Node[]> {
    if (!node) {
      if (!this.reachable) {
        return [{ kind: "message", text: "Server not reachable — run ICM: Start Server" }];
      }
      try {
        this.rounds = await this.client.listRounds();
      } catch (err) {
        return [{ kind: "message", text: `Error: ${(err as Error).message}` }];
      }
      return this.rounds.map((round) => ({ kind: "round", round }));
    }
    if (node.kind === "round") {
      const children: Node[] = node.round.stages.map((stageRef, index) => ({
        kind: "stage",
        round: node.round,
        stageRef,
        index,
      }));
      children.push({ kind: "artifacts", round: node.round });
      return children;
    }
    if (node.kind === "artifacts") {
      try {
        const detail = await this.client.getRound(node.round.round_id);
        if (detail.artifacts.length === 0) {
          return [{ kind: "message", text: "No artifacts yet" }];
        }
        return detail.artifacts.map((artifact) => ({ kind: "artifact", artifact }));
      } catch (err) {
        return [{ kind: "message", text: `Error: ${(err as Error).message}` }];
      }
    }
    return [];
  }

  private roundItem(round: Round): vscode.TreeItem {
    const item = new vscode.TreeItem(
      truncateObjective(round.objective),
      vscode.TreeItemCollapsibleState.Collapsed,
    );
    const stage = round.current_stage ? ` · ${round.current_stage}` : "";
    item.description = `${round.status}${stage}`;
    item.iconPath = new vscode.ThemeIcon(statusIcon(round.status));
    item.contextValue = `round-${round.status}`;
    item.id = round.round_id;
    const mode = round.route.join(" → ");
    item.tooltip = new vscode.MarkdownString(
      [
        `**${round.objective}**`,
        "",
        `- id: \`${round.round_id}\``,
        `- status: ${round.status}`,
        `- mode: ${mode || "—"}`,
        round.route_reason ? `- reason: ${round.route_reason}` : "",
        round.active_gate ? `- gate: ${round.active_gate}` : "",
        round.last_error ? `- error: ${round.last_error}` : "",
        round.workspace_path ? `- worktree: \`${round.workspace_path}\`` : "",
      ]
        .filter(Boolean)
        .join("\n"),
    );
    return item;
  }

  private stageItem(node: StageNode): vscode.TreeItem {
    const item = new vscode.TreeItem(node.stageRef, vscode.TreeItemCollapsibleState.None);
    const state = stageState(node.round, node.stageRef, node.index);
    item.iconPath = new vscode.ThemeIcon(state.icon);
    item.description = state.label;
    item.contextValue = "stage";
    return item;
  }

  private artifactItem(artifact: ArtifactRecord): vscode.TreeItem {
    const item = new vscode.TreeItem(artifact.name, vscode.TreeItemCollapsibleState.None);
    item.description = `${artifact.stage_ref} · ${artifact.size}B`;
    item.iconPath = new vscode.ThemeIcon("file");
    item.contextValue = "artifact";
    item.tooltip = `${artifact.relative_path}\nsha256: ${artifact.sha256}`;
    item.command = {
      command: "icm.openArtifact",
      title: "Open Artifact",
      arguments: [artifact.id],
    };
    return item;
  }
}
