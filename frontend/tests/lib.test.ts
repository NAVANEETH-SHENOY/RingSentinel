import { describe, expect, it } from "vitest";
import { formatInr, formatPercent, formatTimestamp, shortHash } from "@/lib/format";
import { parseMarkdownTable } from "@/lib/markdownTable";
import { ablationTable, costCurve, costRows, detectorSummaries, prSeries, robustnessRows } from "@/lib/metricsView";
import type { MetricsDoc } from "@/lib/types";
import { demoDoc } from "./helpers";

describe("format", () => {
  it("groups rupees the Indian way and handles bad values", () => {
    expect(formatInr(1234567)).toBe("₹12,34,567");
    expect(formatInr(-250)).toBe("-₹250");
    expect(formatInr(null)).toBe("n/a");
    expect(formatInr(Number.NaN)).toBe("n/a");
  });
  it("formats percents, timestamps and hashes", () => {
    expect(formatPercent(0.1234)).toBe("12.3%");
    expect(formatTimestamp("2022-09-01T10:00:00")).toBe("2022-09-01 10:00");
    expect(formatTimestamp("weird")).toBe("weird");
    expect(shortHash("abcdef0123456789")).toBe("abcdef01");
    expect(shortHash(null)).toBe("n/a");
  });
});

describe("parseMarkdownTable", () => {
  it("parses the first pipe table and pads short rows", () => {
    const t = parseMarkdownTable("intro\n\n| a | b |\n|---|:--:|\n| 1 | 2 |\n| 3 |\n\nafter");
    expect(t).toEqual({ header: ["a", "b"], rows: [["1", "2"], ["3", ""]] });
  });
  it("returns null when there is no table", () => {
    expect(parseMarkdownTable("just text | with a pipe")).toBeNull();
    expect(parseMarkdownTable(null)).toBeNull();
  });
});

describe("metricsView adapters (layout assumed from docs/PROJECT_EXPLAINER.md D9; not yet seen on real output)", () => {
  const doc = demoDoc<MetricsDoc>("metrics.json");
  it("reads detector summaries", () => {
    const s = detectorSummaries(doc);
    expect(s.map((x) => x.detector)).toEqual(["iforest", "velocity", "xgb_graph", "xgb_tabular"]);
    expect(s.find((x) => x.detector === "xgb_graph")).toMatchObject({ prAuc: 0.047, positives: 1500 });
  });
  it("reads PR series sorted by recall", () => {
    const pr = prSeries(doc)!;
    expect(pr).toHaveLength(4);
    expect(pr[0]!.points.map((p) => p.x)).toEqual([...pr[0]!.points.map((p) => p.x)].sort((a, b) => a - b));
  });
  it("reads the cost sweep and builds a curve for one setting", () => {
    const rows = costRows(doc)!;
    expect(rows).toHaveLength(4 * 36);
    const curve = costCurve(rows, 1, 250);
    expect(curve).toHaveLength(4);
    expect(curve[0]!.points).toHaveLength(4);
  });
  it("accepts a cost sweep given as one flat array with a detector field and short key names", () => {
    const rows = costRows({ ...doc, cost_sweep: [{ detector: "d", capture: 1, review: 250, fp: 500, net_value: 10 }] } as MetricsDoc);
    expect(rows).toEqual([{ detector: "d", capture: 1, review: 250, fp: 500, netValue: 10 }]);
  });
  it("returns null for shapes it does not know instead of guessing", () => {
    const empty = { schema_version: "1", meta: {}, detectors: { a: { test: { pr_auc: 0.1, "ring_pr_tau_0.5": "oops" } } }, cost_sweep: { a: "x" } } as unknown as MetricsDoc;
    expect(prSeries(empty)).toBeNull();
    expect(costRows(empty)).toBeNull();
    expect(ablationTable(empty)).toBeNull();
    expect(robustnessRows(empty)).toBeNull();
  });
  it("flattens ablation summaries into columns", () => {
    const t = ablationTable(doc)!;
    expect(t.rows).toHaveLength(3);
    expect(t.columns).toContain("summary.test_pr_auc");
  });
  it("sorts robustness levels", () => {
    const r = robustnessRows(doc)!;
    expect(r.map((x) => x.dropout)).toEqual([0, 0.1, 0.2, 0.3, 0.5]);
  });
});

import { seriesColors } from "@/components/charts";
describe("seriesColors (colour follows the entity)", () => {
  it("gives a known detector the same colour whatever the order", () => {
    const a = seriesColors(["xgb_graph", "velocity"]);
    const b = seriesColors(["velocity", "xgb_graph"]);
    expect(a[0]).toBe(b[1]);
    expect(a[1]).toBe(b[0]);
  });
  it("gives unknown names distinct, unused slots", () => {
    const c = seriesColors(["xgb_graph", "mystery", "other"]);
    expect(new Set(c).size).toBe(3);
  });
});

import { layoutGraph } from "@/lib/graph";
describe("charts end labels", () => {
  it("is covered by the page tests; layout grows with node count", () => {
    const nodes = Array.from({ length: 400 }, (_, i) => ({ id: `n${i}`, strength: 1, inInr: 0, outInr: 1, degree: 1, isMember: true }));
    expect(layoutGraph({ nodes, edges: [] }).width).toBeGreaterThan(layoutGraph({ nodes: nodes.slice(0, 10), edges: [] }).width);
  });
});
