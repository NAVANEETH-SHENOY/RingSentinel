"use client";
import { formatNumber } from "@/lib/format";
import type { Series } from "@/lib/metricsView";

export const SERIES_COLORS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"];

/** Colour follows the entity, not its position in the list: a detector keeps its colour on every
 *  chart and after any re-ordering. Unknown names take the next free slot. */
const KNOWN_SLOTS: Record<string, number> = { xgb_graph: 0, xgb_tabular: 1, velocity: 2, iforest: 3 };

export function seriesColors(names: string[]): string[] {
  const used = new Set<number>();
  const slots = names.map((n) => {
    const k = KNOWN_SLOTS[n];
    if (k !== undefined) used.add(k);
    return k;
  });
  let next = 0;
  return slots.map((k) => {
    if (k !== undefined) return SERIES_COLORS[k] as string;
    while (used.has(next) && next < SERIES_COLORS.length) next += 1;
    const slot = next % SERIES_COLORS.length;
    used.add(next);
    return SERIES_COLORS[slot] as string;
  });
}
const W = 640;
const H = 320;
const M = { top: 16, right: 88, bottom: 44, left: 72 };

function niceTicks(min: number, max: number, n = 5): number[] {
  if (min === max) return [min];
  const step = (max - min) / (n - 1);
  return Array.from({ length: n }, (_, i) => min + i * step);
}

/** Line chart with a legend, end-of-line direct labels and a table view (colour is never the
 *  only cue: the lightest series colours are below 3:1 on white, so the labels and the table are
 *  required, not decorative). */
export function LineChart(props: {
  title: string;
  series: Series[];
  xLabel: string;
  yLabel: string;
  xFormat?: (v: number) => string;
  yFormat?: (v: number) => string;
  yMin?: number;
  yMax?: number;
}) {
  const { title, series, xLabel, yLabel } = props;
  const xf = props.xFormat ?? formatNumber;
  const yf = props.yFormat ?? formatNumber;
  const colors = seriesColors(series.map((s) => s.name));
  const pts = series.flatMap((s) => s.points);
  if (pts.length === 0) return <p className="muted">No points to draw.</p>;
  const xs = pts.map((p) => p.x);
  const ys = pts.map((p) => p.y);
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const yMin = props.yMin ?? Math.min(0, ...ys);
  const yMax = props.yMax ?? Math.max(...ys);
  const sy0 = (v: number) => H - M.bottom - (yMax === yMin ? 0.5 : (v - yMin) / (yMax - yMin)) * (H - M.top - M.bottom);
  // End-of-line labels: sort by height and push apart so they never overlap.
  const ends = series
    .map((s, i) => ({ i, y: s.points.length ? sy0(s.points[s.points.length - 1]!.y) : 0 }))
    .sort((a, b) => a.y - b.y);
  for (let k = 1; k < ends.length; k += 1) ends[k]!.y = Math.max(ends[k]!.y, ends[k - 1]!.y + 13);
  const bottom = H - M.bottom;
  const overflow = (ends[ends.length - 1]?.y ?? 0) - bottom;
  if (overflow > 0) {
    for (const e of ends) e.y -= overflow;
    for (let k = ends.length - 2; k >= 0; k -= 1) ends[k]!.y = Math.min(ends[k]!.y, ends[k + 1]!.y - 13);
  }
  const labelY = new Map(ends.map((e) => [e.i, e.y]));
  const sx = (v: number) => M.left + (xMax === xMin ? 0.5 : (v - xMin) / (xMax - xMin)) * (W - M.left - M.right);
  function sy(v: number) {
    return sy0(v);
  }
  return (
    <figure style={{ margin: 0 }}>
      <figcaption style={{ fontWeight: 600, marginBottom: 4 }}>{title}</figcaption>
      <div className="legend" aria-label="Legend">
        {series.map((s, i) => (
          <span key={s.name}>
            <i style={{ background: colors[i] }} />
            {s.name}
          </span>
        ))}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}. ${series.length} series. Table view below.`} style={{ width: "100%", maxWidth: 760, height: "auto" }}>
        {niceTicks(yMin, yMax).map((t) => (
          <g key={`y${t}`}>
            <line x1={M.left} x2={W - M.right} y1={sy(t)} y2={sy(t)} stroke="#dde3ec" strokeWidth="1" />
            <text x={M.left - 8} y={sy(t) + 4} textAnchor="end" fontSize="11" fill="#43546f">{yf(t)}</text>
          </g>
        ))}
        {niceTicks(xMin, xMax).map((t) => (
          <text key={`x${t}`} x={sx(t)} y={H - M.bottom + 16} textAnchor="middle" fontSize="11" fill="#43546f">{xf(t)}</text>
        ))}
        <text x={(M.left + W - M.right) / 2} y={H - 6} textAnchor="middle" fontSize="12" fill="#43546f">{xLabel}</text>
        <text transform={`translate(14 ${(M.top + H - M.bottom) / 2}) rotate(-90)`} textAnchor="middle" fontSize="12" fill="#43546f">{yLabel}</text>
        {series.map((s, i) => {
          const color = colors[i] as string;
          const d = s.points.map((p, j) => `${j === 0 ? "M" : "L"}${sx(p.x).toFixed(1)} ${sy(p.y).toFixed(1)}`).join(" ");
          const last = s.points[s.points.length - 1];
          return (
            <g key={s.name}>
              <path d={d} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
              {s.points.length <= 40 && s.points.map((p) => <circle key={`${p.x}-${p.y}`} cx={sx(p.x)} cy={sy(p.y)} r="3.5" fill={color} stroke="#fff" strokeWidth="2" />)}
              {last && series.length > 1 && (
                <text x={W - M.right + 8} y={(labelY.get(i) ?? sy(last.y)) + 4} fontSize="11" fill="#0c2451" fontWeight="600">{s.name}</text>
              )}
            </g>
          );
        })}
      </svg>
      <details>
        <summary>Table view</summary>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th scope="col">Series</th><th scope="col" className="num">{xLabel}</th><th scope="col" className="num">{yLabel}</th></tr>
            </thead>
            <tbody>
              {series.flatMap((s) => s.points.map((p) => (
                <tr key={`${s.name}-${p.x}-${p.y}`}><td>{s.name}</td><td className="num">{xf(p.x)}</td><td className="num">{yf(p.y)}</td></tr>
              )))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}

/** Horizontal bars for one measure per detector, value printed at the end of each bar. */
export function HBars(props: { title: string; rows: { label: string; value: number }[]; format?: (v: number) => string }) {
  const f = props.format ?? formatNumber;
  const max = Math.max(...props.rows.map((r) => r.value), 1e-9);
  const colors = seriesColors(props.rows.map((r) => r.label));
  return (
    <figure style={{ margin: 0 }}>
      <figcaption style={{ fontWeight: 600, marginBottom: 8 }}>{props.title}</figcaption>
      <div style={{ display: "grid", gap: 8 }}>
        {props.rows.map((r, i) => (
          <div key={r.label} style={{ display: "grid", gridTemplateColumns: "150px 1fr 70px", gap: 10, alignItems: "center" }}>
            <span className="small">{r.label}</span>
            <div style={{ background: "var(--surface-2)", borderRadius: 4 }}>
              <div style={{ width: `${Math.max(2, (r.value / max) * 100)}%`, height: 10, borderRadius: 4, background: colors[i] }} />
            </div>
            <span className="small num">{f(r.value)}</span>
          </div>
        ))}
      </div>
    </figure>
  );
}
