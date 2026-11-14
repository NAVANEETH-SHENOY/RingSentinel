/** Turns the Stage 03 metrics document into view models for the dashboard.
 *
 *  The exact key names inside metrics.json come from Stage 03 (documented in
 *  docs/PROJECT_EXPLAINER.md, D9). They have NOT been checked against real Stage 03 output, which
 *  does not exist yet, so every extractor is tolerant: unknown shapes give `null`, and the page
 *  then shows an explicit "not recognised in this bundle" state next to the raw JSON.
 */

import type { Json, JsonObject, MetricsDoc } from "./types";

export const isObj = (v: unknown): v is JsonObject => typeof v === "object" && v !== null && !Array.isArray(v);
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

function firstNum(o: JsonObject, keys: string[]): number | undefined {
  for (const k of keys) {
    const v = o[k];
    if (isNum(v)) return v;
  }
  return undefined;
}

/** Flatten numeric/string scalars up to `depth` levels, with dotted keys. */
export function flattenScalars(o: JsonObject, depth = 2, prefix = ""): Record<string, number | string> {
  const out: Record<string, number | string> = {};
  for (const [k, v] of Object.entries(o)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (isNum(v) || typeof v === "string") out[key] = v;
    else if (isObj(v) && depth > 0) Object.assign(out, flattenScalars(v, depth - 1, key));
  }
  return out;
}

export interface DetectorSummary {
  detector: string;
  prAuc?: number;
  prevalence?: number;
  positives?: number;
}

export function detectorSummaries(doc: MetricsDoc): DetectorSummary[] {
  if (!isObj(doc.detectors)) return [];
  return Object.entries(doc.detectors)
    .filter((e): e is [string, JsonObject] => isObj(e[1]))
    .map(([detector, d]) => {
      const test = isObj(d.test) ? d.test : {};
      return {
        detector,
        prAuc: firstNum(test, ["pr_auc"]),
        prevalence: firstNum(test, ["prevalence"]),
        positives: firstNum(test, ["positives"]),
      };
    });
}

export interface Point {
  x: number;
  y: number;
}
export interface Series {
  name: string;
  points: Point[];
}

function toPoints(raw: Json | undefined): Point[] | null {
  const arr = Array.isArray(raw) ? raw : isObj(raw) ? (raw.points ?? raw.curve) : null;
  if (!Array.isArray(arr)) return null;
  const pts: Point[] = [];
  for (const item of arr) {
    if (!isObj(item)) continue;
    const recall = firstNum(item, ["recall", "r"]);
    const precision = firstNum(item, ["precision", "p"]);
    if (recall !== undefined && precision !== undefined) pts.push({ x: recall, y: precision });
  }
  if (pts.length === 0) return null;
  return pts.sort((a, b) => a.x - b.x || a.y - b.y);
}

/** Ring-level precision/recall points on the test split at tau 0.5, one series per detector. */
export function prSeries(doc: MetricsDoc): Series[] | null {
  if (!isObj(doc.detectors)) return null;
  const out: Series[] = [];
  for (const [name, d] of Object.entries(doc.detectors)) {
    if (!isObj(d)) continue;
    const test = isObj(d.test) ? d.test : {};
    const pts = toPoints(test["ring_pr_tau_0.5"]) ?? toPoints(d["ring_pr_tau_0.5"]);
    if (pts) out.push({ name, points: pts });
  }
  return out.length ? out : null;
}

export interface CostRow {
  detector: string;
  capture: number;
  review: number;
  fp: number;
  netValue: number;
}

function toCostRow(detector: string, r: JsonObject): CostRow | null {
  const capture = firstNum(r, ["capture", "loss_capture_rate", "capture_rate"]);
  const review = firstNum(r, ["review", "review_cost_inr", "review_cost", "c_review"]);
  const fp = firstNum(r, ["fp", "fp_cost_inr", "fp_cost", "c_fp"]);
  const netValue = firstNum(r, ["test_net_value_inr", "net_value_inr", "test_net_value", "net_value"]);
  if (capture === undefined || review === undefined || fp === undefined || netValue === undefined) return null;
  return { detector, capture, review, fp, netValue };
}

export function costRows(doc: MetricsDoc): CostRow[] | null {
  const sweep = doc.cost_sweep;
  const rows: CostRow[] = [];
  const add = (detector: string, list: Json) => {
    if (!Array.isArray(list)) return;
    for (const r of list) {
      if (!isObj(r)) continue;
      const row = toCostRow(typeof r.detector === "string" ? r.detector : detector, r);
      if (row) rows.push(row);
    }
  };
  if (Array.isArray(sweep)) add("detector", sweep);
  else if (isObj(sweep)) {
    for (const [name, v] of Object.entries(sweep)) {
      if (Array.isArray(v)) add(name, v);
      else if (isObj(v)) add(name, (v.rows as Json) ?? (v.sweep as Json) ?? null);
    }
  }
  return rows.length ? rows : null;
}

export const uniqueSorted = (values: number[]) => [...new Set(values)].sort((a, b) => a - b);

/** Net value against the false-positive cost at one fixed (capture, review) setting. */
export function costCurve(rows: CostRow[], capture: number, review: number): Series[] {
  const byDet = new Map<string, Point[]>();
  for (const r of rows) {
    if (r.capture !== capture || r.review !== review) continue;
    const list = byDet.get(r.detector) ?? [];
    list.push({ x: r.fp, y: r.netValue });
    byDet.set(r.detector, list);
  }
  return [...byDet.entries()].map(([name, pts]) => ({ name, points: pts.sort((a, b) => a.x - b.x) }));
}

export interface GenericTable {
  columns: string[];
  rows: { label: string; values: Record<string, number | string> }[];
}

function tableFrom(entries: [string, JsonObject][], maxCols = 8): GenericTable | null {
  if (entries.length === 0) return null;
  const columns: string[] = [];
  const rows = entries.map(([label, o]) => {
    const values = flattenScalars(o);
    for (const k of Object.keys(values)) if (!columns.includes(k) && columns.length < maxCols) columns.push(k);
    return { label, values };
  });
  return { columns, rows };
}

export function ablationTable(doc: MetricsDoc): GenericTable | null {
  const variants = doc.ablations && isObj(doc.ablations) ? doc.ablations.variants : null;
  if (!isObj(variants)) return null;
  const entries = Object.entries(variants).filter((e): e is [string, JsonObject] => isObj(e[1]));
  return tableFrom(entries);
}

export function latencyTable(doc: MetricsDoc): GenericTable | null {
  if (!doc.latency || !isObj(doc.latency)) return null;
  const entries = Object.entries(doc.latency).filter((e): e is [string, JsonObject] => isObj(e[1]));
  return tableFrom(entries);
}

export interface RobustnessRow {
  dropout: number;
  testPrAuc?: number;
  relative?: number;
  eventsKept?: number;
  ringsAtF1?: number;
  ringsAtNv?: number;
}

export function robustnessRows(doc: MetricsDoc): RobustnessRow[] | null {
  const levels = doc.robustness && isObj(doc.robustness) ? doc.robustness.levels : null;
  if (!Array.isArray(levels)) return null;
  const rows: RobustnessRow[] = [];
  for (const l of levels) {
    if (!isObj(l)) continue;
    const dropout = firstNum(l, ["dropout"]);
    if (dropout === undefined) continue;
    rows.push({
      dropout,
      testPrAuc: firstNum(l, ["test_pr_auc"]),
      relative: firstNum(l, ["pr_auc_relative_to_no_dropout"]),
      eventsKept: firstNum(l, ["events_kept"]),
      ringsAtF1: firstNum(l, ["rings_at_f1_threshold"]),
      ringsAtNv: firstNum(l, ["rings_at_nv_threshold"]),
    });
  }
  return rows.length ? rows.sort((a, b) => a.dropout - b.dropout) : null;
}
