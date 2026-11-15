"use client";
import { formatNumber, formatTimestamp } from "@/lib/format";
import type { DriftWindow, ReplayDoc } from "@/lib/types";

const W = 640;
const H = 300;
const M = { top: 20, right: 16, bottom: 52, left: 56 };

const LEVEL_FILL: Record<DriftWindow["level"], string> = {
  ok: "var(--series-1)",
  warn: "var(--series-4)",
  alert: "var(--danger)",
  insufficient: "var(--border)",
};
const LEVEL_TEXT: Record<DriftWindow["level"], string> = { ok: "", warn: "warn", alert: "ALERT", insufficient: "too few" };

/** PSI per time window as bars, with the warn and alert levels drawn as dashed lines. The level
 *  is also written above every bar that is not "ok" (colour alone never carries the alert). */
export function DriftChart(props: { windows: DriftWindow[]; warn: number; alert: number }) {
  const { windows, warn, alert } = props;
  const values = windows.map((w) => w.psi ?? 0);
  const yMax = Math.max(alert * 1.25, ...values) * 1.05;
  const plotW = W - M.left - M.right;
  const plotH = H - M.top - M.bottom;
  const slot = windows.length ? plotW / windows.length : plotW;
  const sy = (v: number) => H - M.bottom - (v / yMax) * plotH;
  const ticks = [0, yMax / 4, yMax / 2, (3 * yMax) / 4, yMax];
  return (
    <figure style={{ margin: 0 }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Population stability index per time window. ${windows.filter((w) => w.level === "alert").length} window(s) above the alert level ${alert}.`}
        style={{ width: "100%", maxWidth: 760, height: "auto" }}
        data-testid="drift-chart"
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={M.left} x2={W - M.right} y1={sy(t)} y2={sy(t)} stroke="#dde3ec" strokeWidth="1" />
            <text x={M.left - 8} y={sy(t) + 4} textAnchor="end" fontSize="11" fill="#43546f">
              {t.toFixed(2)}
            </text>
          </g>
        ))}
        {windows.map((w, i) => {
          const x = M.left + i * slot + slot * 0.18;
          const bw = slot * 0.64;
          const v = w.psi ?? 0;
          const top = sy(v);
          return (
            <g key={w.index} data-testid="drift-bar" data-level={w.level}>
              <rect x={x} y={top} width={bw} height={Math.max(1, H - M.bottom - top)} rx="3" fill={LEVEL_FILL[w.level]} />
              {LEVEL_TEXT[w.level] && (
                <text x={x + bw / 2} y={top - 5} textAnchor="middle" fontSize="11" fontWeight="700" fill="#0c2451">
                  {LEVEL_TEXT[w.level]}
                </text>
              )}
              <text x={x + bw / 2} y={H - M.bottom + 16} textAnchor="middle" fontSize="11" fill="#43546f">
                W{w.index + 1}
              </text>
              {(i === 0 || i === windows.length - 1) && (
                <text x={x + bw / 2} y={H - M.bottom + 30} textAnchor="middle" fontSize="10" fill="#43546f">
                  {formatTimestamp(w.start_ts).slice(5, 10)}
                </text>
              )}
            </g>
          );
        })}
        {[
          { v: warn, label: `warn ${warn}` },
          { v: alert, label: `alert ${alert}` },
        ].map((r) => (
          <g key={r.label}>
            <line x1={M.left} x2={W - M.right} y1={sy(r.v)} y2={sy(r.v)} stroke="#0c2451" strokeDasharray="5 4" strokeWidth="1.2" />
            <text x={M.left + 4} y={sy(r.v) - 4} textAnchor="start" fontSize="10.5" fill="#0c2451">
              {r.label}
            </text>
          </g>
        ))}
        <text transform={`translate(14 ${(M.top + H - M.bottom) / 2}) rotate(-90)`} textAnchor="middle" fontSize="12" fill="#43546f">
          PSI vs validation scores
        </text>
      </svg>
    </figure>
  );
}

/** Test events per time step as bars, a marker for each ring detected in that step, and a cursor. */
export function TimelineChart(props: { timeline: NonNullable<ReplayDoc["timeline"]>; cursor: number }) {
  const { timeline: t, cursor } = props;
  const n = t.n_steps;
  const plotW = W - M.left - M.right;
  const plotH = H - M.top - M.bottom - 24;
  const slot = plotW / n;
  const yMax = Math.max(1, ...t.events);
  const base = H - M.bottom;
  return (
    <figure style={{ margin: 0 }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Transfers over time with ${t.detected.reduce((a, b) => a + b, 0)} ring detections marked.`}
        style={{ width: "100%", maxWidth: 760, height: "auto" }}
        data-testid="timeline-chart"
      >
        <line x1={M.left} x2={W - M.right} y1={base} y2={base} stroke="#dde3ec" />
        <text x={M.left - 8} y={base + 4} textAnchor="end" fontSize="11" fill="#43546f">0</text>
        <text x={M.left - 8} y={base - plotH + 4} textAnchor="end" fontSize="11" fill="#43546f">{formatNumber(yMax)}</text>
        {t.events.map((v, i) => {
          const h = (v / yMax) * plotH;
          return (
            <rect
              key={i}
              x={M.left + i * slot + 0.5}
              y={base - h}
              width={Math.max(1, slot - 1)}
              height={h}
              fill={i <= cursor ? "var(--series-1)" : "#c9d7ea"}
            />
          );
        })}
        {t.detected.map((d, i) =>
          d > 0 ? (
            <g key={`d${i}`} data-testid="detect-marker">
              <path
                d={`M${M.left + i * slot + slot / 2} ${base + 6} l-5 9 h10 z`}
                fill={i <= cursor ? "var(--danger)" : "none"}
                stroke="var(--danger)"
                strokeWidth="1.5"
              />
              {d > 1 && (
                <text x={M.left + i * slot + slot / 2} y={base + 28} textAnchor="middle" fontSize="10" fill="#0c2451">
                  {d}
                </text>
              )}
            </g>
          ) : null,
        )}
        <line
          x1={M.left + (cursor + 1) * slot}
          x2={M.left + (cursor + 1) * slot}
          y1={M.top}
          y2={base}
          stroke="#0c2451"
          strokeWidth="1.5"
          data-testid="timeline-cursor"
        />
        <text x={M.left} y={H - 8} fontSize="11" fill="#43546f">{formatTimestamp(t.start_ts)}</text>
        <text x={W - M.right} y={H - 8} textAnchor="end" fontSize="11" fill="#43546f">{formatTimestamp(t.end_ts)}</text>
      </svg>
      <p className="small muted">Bars: all test transfers per step. Triangles: a ring becomes detectable in that step (filled once the cursor has passed it).</p>
    </figure>
  );
}
