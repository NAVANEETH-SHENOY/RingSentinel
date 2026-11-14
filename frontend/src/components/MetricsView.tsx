"use client";
import { useMemo, useState, type ReactNode } from "react";
import { HBars, LineChart } from "./charts";
import { OriginNote, Resource } from "./DataState";
import { formatInr, formatNumber, formatPercent, humanizeKey } from "@/lib/format";
import { parseMarkdownTable } from "@/lib/markdownTable";
import {
  ablationTable,
  costCurve,
  costRows,
  detectorSummaries,
  latencyTable,
  prSeries,
  robustnessRows,
  uniqueSorted,
  type GenericTable,
} from "@/lib/metricsView";
import { useSource } from "@/lib/SourceContext";
import { useResource } from "@/lib/useResource";
import type { MetricsDoc } from "@/lib/types";

export function MetricsView() {
  const source = useSource();
  const { state, reload } = useResource(() => source.metrics(), [source]);
  return (
    <>
      <h1>Metrics</h1>
      <p className="muted">How each detector did on the held-out test split, and what the false alarms cost.</p>
      <Resource state={state} onRetry={reload} loadingLabel="Loading metrics">
        {(loaded) => (
          <>
            <OriginNote loaded={loaded} />
            <MetricsBody doc={loaded.data} />
          </>
        )}
      </Resource>
    </>
  );
}

function Panel({ id, title, note, children }: { id: string; title: string; note?: string; children: ReactNode }) {
  return (
    <section className="card" aria-labelledby={id}>
      <h2 id={id}>{title}</h2>
      {children}
      {note && <p className="small muted">{note}</p>}
    </section>
  );
}

function NotInBundle({ what }: { what: string }) {
  return (
    <p className="muted" data-testid="not-in-bundle">
      {what} is not in this bundle, or its layout is not one this version of the interface recognises. The raw document is at the bottom of the page.
    </p>
  );
}

function GenericTableView({ table }: { table: GenericTable }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th scope="col">Name</th>
            {table.columns.map((c) => (
              <th key={c} scope="col" className="num">{humanizeKey(c)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((r) => (
            <tr key={r.label}>
              <th scope="row">{r.label}</th>
              {table.columns.map((c) => {
                const v = r.values[c];
                return <td key={c} className="num">{typeof v === "number" ? formatNumber(v) : (v ?? "")}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function MetricsBody({ doc }: { doc: MetricsDoc }) {
  const summaries = useMemo(() => detectorSummaries(doc), [doc]);
  const table = useMemo(() => parseMarkdownTable(doc.results_table_md), [doc]);
  const pr = useMemo(() => prSeries(doc), [doc]);
  const cost = useMemo(() => costRows(doc), [doc]);
  const ablations = useMemo(() => ablationTable(doc), [doc]);
  const robustness = useMemo(() => robustnessRows(doc), [doc]);
  const latency = useMemo(() => latencyTable(doc), [doc]);
  const prevalence = summaries.find((s) => s.prevalence !== undefined)?.prevalence;

  return (
    <>
      <Panel id="prov-h" title="What these numbers are">
        <p className="small">
          Frozen: <strong>{doc.evaluation_frozen ? "yes" : "no (provisional)"}</strong>. The test split was scored once per detector; thresholds were chosen on validation. Rupee costs are planning assumptions.
        </p>
        <ProvenanceMeta meta={doc.meta} />
      </Panel>

      <Panel id="cmp-h" title="Detector comparison" note="Strict ring precision is pessimistic: real laundering outside the known pattern rings counts as a false ring. See docs/EVALUATION.md.">
        {table ? (
          <div className="table-wrap" data-testid="results-table">
            <table>
              <thead>
                <tr>{table.header.map((h) => <th key={h} scope="col">{h}</th>)}</tr>
              </thead>
              <tbody>
                {table.rows.map((r) => (
                  <tr key={r.join("|")}>{r.map((cell, i) => (i === 0 ? <th key={i} scope="row">{cell}</th> : <td key={i}>{cell}</td>))}</tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : summaries.length > 0 ? (
          <div className="table-wrap" data-testid="summary-table">
            <table>
              <thead>
                <tr><th scope="col">Detector</th><th scope="col" className="num">Test PR-AUC</th><th scope="col" className="num">Prevalence</th><th scope="col" className="num">Positives</th></tr>
              </thead>
              <tbody>
                {summaries.map((s) => (
                  <tr key={s.detector}>
                    <th scope="row">{s.detector}</th>
                    <td className="num">{s.prAuc === undefined ? "n/a" : s.prAuc.toFixed(4)}</td>
                    <td className="num">{formatPercent(s.prevalence, 3)}</td>
                    <td className="num">{formatNumber(s.positives)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <NotInBundle what="The detector comparison" />
        )}
        {summaries.some((s) => s.prAuc !== undefined) && (
          <div style={{ marginTop: 20 }}>
            <HBars title="Test PR-AUC (transaction level)" rows={summaries.filter((s) => s.prAuc !== undefined).map((s) => ({ label: s.detector, value: s.prAuc as number }))} format={(v) => v.toFixed(4)} />
            {prevalence !== undefined && <p className="small muted">A random ranking scores about the prevalence: {formatPercent(prevalence, 3)}.</p>}
          </div>
        )}
      </Panel>

      <Panel id="pr-h" title="Precision and recall (ring level, test split)">
        {pr ? (
          <LineChart title="Ring-level precision against recall at tau 0.5" series={pr} xLabel="Recall" yLabel="Precision" yMin={0} yMax={1} xFormat={(v) => v.toFixed(2)} yFormat={(v) => v.toFixed(2)} />
        ) : (
          <NotInBundle what="The ring-level precision-recall curve" />
        )}
      </Panel>

      <Panel id="cost-h" title="Cost curve" note="Net value on the test split when the false-positive cost changes; the threshold is re-chosen on validation for every setting. Rupee figures are planning assumptions.">
        {cost ? <CostCurvePanel rows={cost} /> : <NotInBundle what="The cost sweep" />}
      </Panel>

      <Panel id="abl-h" title="Ablations" note="Does hub control help, and do graph features help? Read the numbers, including any that disappoint.">
        {ablations ? <GenericTableView table={ablations} /> : <NotInBundle what="The ablation table" />}
      </Panel>

      <Panel id="rob-h" title="Robustness to missing transfers" note="Random removal of transfers is used only to test how the detector decays; it is not an evasion tool.">
        {robustness ? (
          <>
            {robustness.some((r) => r.testPrAuc !== undefined) && (
              <LineChart
                title="Test PR-AUC as more transfers are removed"
                series={[{ name: "xgb_graph", points: robustness.filter((r) => r.testPrAuc !== undefined).map((r) => ({ x: r.dropout, y: r.testPrAuc as number })) }]}
                xLabel="Share of transfers removed"
                yLabel="PR-AUC"
                yMin={0}
                xFormat={(v) => formatPercent(v, 0)}
                yFormat={(v) => v.toFixed(3)}
              />
            )}
            <div className="table-wrap" style={{ marginTop: 12 }}>
              <table>
                <thead>
                  <tr><th scope="col" className="num">Removed</th><th scope="col" className="num">Events kept</th><th scope="col" className="num">Test PR-AUC</th><th scope="col" className="num">Relative to none removed</th><th scope="col" className="num">Rings (F1)</th><th scope="col" className="num">Rings (net value)</th></tr>
                </thead>
                <tbody>
                  {robustness.map((r) => (
                    <tr key={r.dropout}>
                      <td className="num">{formatPercent(r.dropout, 0)}</td>
                      <td className="num">{formatNumber(r.eventsKept)}</td>
                      <td className="num">{r.testPrAuc === undefined ? "n/a" : r.testPrAuc.toFixed(4)}</td>
                      <td className="num">{formatPercent(r.relative, 1)}</td>
                      <td className="num">{formatNumber(r.ringsAtF1)}</td>
                      <td className="num">{formatNumber(r.ringsAtNv)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <NotInBundle what="The robustness table" />
        )}
      </Panel>

      <Panel id="lat-h" title="Detection latency" note="Events between the first transfer of a ring and the first flagged transfer. Window-level features make this a lower bound.">
        {latency ? <GenericTableView table={latency} /> : <NotInBundle what="The latency table" />}
      </Panel>

      <details className="card soft">
        <summary>Raw metrics document</summary>
        <pre className="raw">{JSON.stringify({ meta: doc.meta, detectors: doc.detectors, cost_sweep: doc.cost_sweep, ablations: doc.ablations, robustness: doc.robustness, latency: doc.latency }, null, 2)}</pre>
      </details>
    </>
  );
}

function ProvenanceMeta({ meta }: { meta: MetricsDoc["meta"] }) {
  const rows = Object.entries(meta).filter(([, v]) => typeof v === "string" || typeof v === "number");
  if (rows.length === 0) return null;
  return (
    <details>
      <summary>Run details</summary>
      <dl className="small" style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "4px 16px" }}>
        {rows.map(([k, v]) => (
          <div key={k} style={{ display: "contents" }}>
            <dt className="muted">{humanizeKey(k)}</dt>
            <dd style={{ margin: 0 }}>{String(v)}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

function CostCurvePanel({ rows }: { rows: NonNullable<ReturnType<typeof costRows>> }) {
  const captures = uniqueSorted(rows.map((r) => r.capture));
  const reviews = uniqueSorted(rows.map((r) => r.review));
  const [capture, setCapture] = useState(captures[captures.length - 1] ?? 1);
  const [review, setReview] = useState(reviews.includes(250) ? 250 : (reviews[0] ?? 0));
  const series = costCurve(rows, capture, review);
  return (
    <>
      <div className="toolbar">
        <label className="field">
          Capture rate
          <select value={capture} onChange={(e) => setCapture(Number(e.target.value))}>
            {captures.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label className="field">
          Review cost
          <select value={review} onChange={(e) => setReview(Number(e.target.value))}>
            {reviews.map((r) => <option key={r} value={r}>{formatInr(r)}</option>)}
          </select>
        </label>
      </div>
      {series.length === 0 ? (
        <p className="muted">No sweep rows for this setting.</p>
      ) : (
        <LineChart title="Test net value against the cost of wrongly including an account" series={series} xLabel="Cost per wrongly included account (₹)" yLabel="Net value (₹)" xFormat={formatInr} yFormat={formatInr} />
      )}
    </>
  );
}
