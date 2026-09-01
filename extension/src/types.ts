// Shapes mirror the harness HTTP API (src/icm_harness/web/server.py) and the
// dataclasses in src/icm_harness/kernel/state.py. Keep them in sync.

export interface Round {
  round_id: string;
  objective: string;
  route: string[];
  stages: string[];
  cursor: number;
  status: RoundStatus;
  version: number;
  created_at: string;
  updated_at: string;
  profile?: Record<string, unknown> | null;
  route_reason: string;
  active_gate?: string | null;
  cancel_requested: boolean;
  last_error?: string | null;
  workspace_path?: string | null;
  current_stage: string | null;
}

export type RoundStatus =
  | "active"
  | "running"
  | "waiting_approval"
  | "failed"
  | "blocked"
  | "cancelled"
  | "closed";

export interface EventRecord {
  id: number;
  round_id: string;
  stage_ref: string | null;
  kind: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface ArtifactRecord {
  id: number;
  round_id: string;
  stage_ref: string;
  name: string;
  relative_path: string;
  media_type: string;
  sha256: string;
  size: number;
  created_at: string;
}

export interface RoundDetail extends Round {
  events: EventRecord[];
  artifacts: ArtifactRecord[];
  promoted: boolean;
  workspace_diff: string;
}

export interface ArtifactContent extends ArtifactRecord {
  content: string;
}

export interface NewRoundRequest {
  objective: string;
  intent?: string;
  clarity?: number;
  uncertainty?: number;
  stakes?: number;
  reversibility?: number;
  production_change?: boolean;
  code_intensity?: number;
  research_intensity?: number;
  tool_intensity?: number;
  privacy_restricted?: boolean;
  budget_usd?: number | null;
  run?: boolean;
  dry_run?: boolean;
}
