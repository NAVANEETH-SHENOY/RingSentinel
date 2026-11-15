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

export interface LiveFields {
  adjusted_score: number;
  adjusted_expected_value_inr: number;
  above_threshold: boolean;
  /** null for rings that are decided, held-out or below the effective threshold. */
  live_rank: number | null;
}

export interface FeedbackState {
  base_threshold: number | null;
  effective_threshold: number | null;
  offset_logit: number;
  max_offset_logit: number;
  step_logit: number;
  confirm_weight: number;
  at_bound: boolean;
  n_confirmed: number;
  n_dismissed: number;
  n_held: number;
  n_pending: number;
  n_active: number;
  n_deprioritised: number;
  n_in_bundle: number;
  rule: string;
  validated: boolean;
  note: string;
}

export type QueueOrder = "export" | "live";

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
  /** API only: the score and value after the bounded analyst-feedback shift (Stage 07). */
  live?: LiveFields;
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
  /** API only. */
  order?: QueueOrder;
  feedback?: FeedbackState;
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

export type DriftLevel = "ok" | "warn" | "alert" | "insufficient";

export interface DriftWindow {
  index: number;
  start_ts: string;
  end_ts: string;
  n_events: number;
  psi: number | null;
  level: DriftLevel;
  mean_score?: number | null;
  n_positives?: number;
  n_flagged?: number;
  flagged_rate?: number | null;
  precision_at_threshold?: number | null;
  recall_at_threshold?: number | null;
}

export interface DriftDoc {
  schema_version: string;
  bundle_id?: string;
  status: "not_built" | "ready";
  built_in_stage: string;
  detector?: string;
  threshold?: number | null;
  psi_warn_level?: number | null;
  psi_alert_level: number | null;
  reference?: { split: string; n_events: number };
  windows: DriftWindow[];
  summary?: {
    n_windows: number;
    n_scored: number;
    n_alert: number;
    n_warn: number;
    alert_windows: number[];
    max_psi: number | null;
    first_alert_index: number | null;
    test_psi: number | null;
    n_reference: number;
    n_test: number;
  };
  notes?: string[];
}

export interface ReplayEvent {
  ring_id: string;
  rank: number;
  score: number;
  expected_value_inr?: number;
  n_members: number;
  n_transfers: number;
  first_ts: string;
  detected_ts: string;
  partial: boolean;
  assembly_minutes: number;
  assembly_events: number;
  truth_ring_id?: number | null;
  truth_share?: number | null;
  truth_first_ts?: string | null;
  latency_minutes?: number | null;
  latency_events?: number | null;
}

export interface ReplayDoc {
  schema_version: string;
  bundle_id?: string;
  status: "not_built" | "ready";
  built_in_stage: string;
  detector?: string;
  threshold?: number | null;
  min_ring_members?: number;
  timeline?: {
    start_ts: string;
    end_ts: string;
    n_steps: number;
    step_minutes: number;
    events: number[];
    ring_transfers: number[];
    detected: number[];
  };
  events: ReplayEvent[];
  summary?: Record<string, number | null>;
  notes?: string[];
}

export type AnalystAction = "confirm" | "dismiss" | "hold";

export interface ActionBody {
  action: AnalystAction;
  analyst: string;
  note: string;
  idempotency_key: string;
}

export interface ActionResult {
  ring_id: string;
  status: RingStatus;
  replayed: boolean;
  entry: AuditEntry;
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
