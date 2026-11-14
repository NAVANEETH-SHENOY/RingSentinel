/** Types for the snapshot bundle (data stage D12) and the API (D13).
 *  Source of truth: backend/ringsentinel/snapshots/schemas.py and backend/app/schemas.py. */

export const SUPPORTED_SCHEMA_VERSION = "1";

export type RingStatus = "pending" | "confirmed" | "dismissed" | "held";

export interface Feature {
  feature: string;
  mean_contribution: number;
}

export interface CostAssumptions {
  review_cost_inr: number;
  fp_cost_inr: number;
  loss_capture_rate: number;
  note?: string;
}

export interface QueueItem {
  ring_id: string;
  rank: number;
  score: number;
  expected_value_inr: number;
  n_members: number;
  n_transfers: number;
  amount_inr: number;
  oversized: boolean;
  top_features: Feature[];
  /** Present only when the item came from the API; snapshots do not know analyst decisions. */
  status?: RingStatus;
}

export interface Queue {
  schema_version: string;
  bundle_id?: string;
  detector: string;
  split: string;
  threshold: number | null;
  threshold_kind: string;
  score_calibrated: false;
  value_formula: string;
  cost_assumptions: CostAssumptions;
  note?: string;
  items: QueueItem[];
}

export interface Edge {
  src: string;
  dst: string;
  n_transfers: number;
  total_inr: number;
  first_ts: string;
  last_ts: string;
}

export type AiLevel = "low" | "medium" | "high";

export interface AiClaim {
  metric: string;
  account?: string | null;
  counterparty?: string | null;
  value?: number;
  value_inr?: number;
}

export interface AiFinding {
  text: string;
  nodes?: string[];
  counts?: AiClaim[];
  amounts?: AiClaim[];
}

export interface AiCaseFile {
  pattern: string;
  suspicion: AiLevel;
  summary: string;
  findings: AiFinding[];
  key_accounts?: { account: string; role: string; reason: string }[];
  limits?: string;
  suggested_checks?: string[];
}

export interface AiBenignCase {
  plausibility: AiLevel;
  summary: string;
  hypotheses: { label: string; argument: string; strength: AiLevel; how_to_check?: string }[];
  weakest_point?: string;
}

export interface AiVerifier {
  status: "verified" | "unverified";
  issues?: string[];
  warnings?: string[];
  checked?: number;
  attempts?: number;
}

export interface AiBlock {
  status: "not_built" | "ready";
  built_in_stage: string;
  /** Stage 06: where the text came from. "template" means rule-based, no language model. */
  source?: "llm" | "cache" | "template";
  provider?: { name: string; model: string } | null;
  investigator?: AiCaseFile | null;
  verifier?: AiVerifier | null;
  benign_explanation?: AiBenignCase | null;
  benign_verifier?: AiVerifier | null;
  contested?: boolean;
  contested_reason?: string | null;
  fallback_kind?: string | null;
  fallback_reason?: string | null;
}

export interface Case {
  ring_id: string;
  rank: number;
  score: number;
  expected_value_inr: number;
  amount_inr: number;
  n_members: number;
  n_transfers: number;
  oversized: boolean;
  members: string[];
  members_truncated: boolean;
  top_features: Feature[];
  edges: Edge[];
  edges_available: boolean;
  edges_truncated: boolean;
  ai: AiBlock;
  /** API only. */
  status?: RingStatus;
  n_actions?: number;
}

export interface Meta {
  schema_version: string;
  bundle_id: string;
  dataset_variant: string;
  seed: number;
  git_commit: string;
  evaluation_frozen: boolean;
  detector: string;
  split: string;
  n_rings_total: number;
  n_rings_exported: number;
  max_rings: number;
  sources: Record<string, string>;
  files: Record<string, string>;
}

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type JsonObject = { [key: string]: Json };

export interface MetricsDoc {
  schema_version: string;
  bundle_id?: string;
  evaluation_frozen?: boolean;
  meta: JsonObject;
  detectors: JsonObject;
  cost_sweep: Json;
  ablations?: JsonObject;
  robustness?: JsonObject;
  latency?: JsonObject;
  results_table_md?: string | null;
}

export interface Placeholder {
  schema_version: string;
  status: "not_built" | "ready";
  built_in_stage: string;
  windows?: unknown[];
  events?: unknown[];
  psi_alert_level?: number | null;
}

export interface AuditEntry {
  seq: number;
  ts: string;
  ring_id: string;
  action: "confirm" | "dismiss" | "hold";
  analyst: string;
  note: string;
  idempotency_key: string;
  prev_hash: string;
  hash: string;
}

export interface VerifyResult {
  ok: boolean;
  entries: number;
  head_hash: string | null;
  first_bad_seq: number | null;
  reason: string | null;
}

export interface Health {
  status: string;
  bundle_id: string;
  schema_version: string;
  evaluation_frozen: boolean;
  git_commit: string;
  n_rings: number;
  audit_entries: number;
  actions_enabled: boolean;
}

/** Where a piece of data came from. Shown to the analyst so nothing is silently stale. */
export type Origin = "api" | "snapshot" | "demo";

export interface Loaded<T> {
  data: T;
  origin: Origin;
  /** Set when a preferred source failed and a fallback was used. */
  fallbackReason?: string;
}
