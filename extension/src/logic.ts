// Pure, vscode-free logic so it can be unit-tested outside the extension host.

import * as path from "path";
import { Round, RoundStatus } from "./types";

export const STATUS_ICON: Record<RoundStatus, string> = {
  active: "circle-outline",
  running: "sync~spin",
  waiting_approval: "person",
  failed: "error",
  blocked: "warning",
  cancelled: "circle-slash",
  closed: "pass-filled",
};

export function statusIcon(status: string): string {
  return STATUS_ICON[status as RoundStatus] ?? "circle-outline";
}

export interface StageState {
  icon: string;
  label: string;
}

/** Derive a stage's display state from the round's cursor/status. */
export function stageState(round: Round, stageRef: string, index: number): StageState {
  if (round.status === "closed" || index < round.cursor) {
    return { icon: "pass-filled", label: "done" };
  }
  if (index === round.cursor) {
    if (round.status === "waiting_approval" && round.active_gate === stageRef) {
      return { icon: "person", label: "awaiting approval" };
    }
    if (round.status === "running") {
      return { icon: "sync~spin", label: "running" };
    }
    if (round.status === "failed" || round.status === "blocked") {
      return { icon: "error", label: round.status };
    }
    return { icon: "arrow-right", label: "current" };
  }
  return { icon: "circle-large-outline", label: "pending" };
}

/** Choose an editor language id for an artifact by name/media type. */
export function languageFor(name: string, mediaType: string): string {
  const ext = path.extname(name).toLowerCase();
  if (ext === ".json" || mediaType.includes("json")) {
    return "json";
  }
  if (ext === ".md" || mediaType.includes("markdown")) {
    return "markdown";
  }
  if (ext === ".diff" || ext === ".patch") {
    return "diff";
  }
  return "plaintext";
}

/** Truncate a round objective for a tree label. */
export function truncateObjective(objective: string, max = 60): string {
  return objective.length > max ? `${objective.slice(0, max - 1)}…` : objective;
}
