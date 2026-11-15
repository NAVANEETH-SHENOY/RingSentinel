"use client";
import { useState } from "react";
import { EmptyState, OriginNote, Resource } from "./DataState";
import { TimelineChart } from "./monitorCharts";
import { formatInr, formatNumber, formatScore, formatTimestamp } from "@/lib/format";
import { detectedBy, eventsBy, formatMinutes, stepEndMs } from "@/lib/replayView";
import { useSource } from "@/lib/SourceContext";
import { useResource } from "@/lib/useResource";
import type { ReplayDoc } from "@/lib/types";

export function ReplayView() {
  const source = useSource();
  const { state, reload } = useResource(() => source.replay(), [source]);
  return (
    <>
      <h1>Replay</h1>
      <p className="muted">
        Step through the test period and see when each flagged ring became detectable. The same data always gives the same
        replay.
      </p>
      <Resource state={state} onRetry={reload} loadingLabel="Loading replay">
        {(loaded) => (
          <>
            <OriginNote loaded={loaded} />
            <ReplayBody doc={loaded.data} />
          </>
        )}
      </Resource>
    </>
  );
}

function ReplayBody({ doc }: { doc: ReplayDoc }) {
  const timeline = doc.timeline;
  const last = timeline ? timeline.n_steps - 1 : 0;
  const [cursor, setCursor] = useState(last);
  if (doc.status !== "ready" || !timeline) {
    return (
      <EmptyState title="Replay was not built for this bundle">
        It needs the event table from the data stage. Re-run the export with the events present.
      </EmptyState>
    );
  }
  const seen = detectedBy(doc, cursor);
  const when = new Date(stepEndMs(timeline, cursor)).toISOString().slice(0, 16).replace("T", " ");
  const s = doc.summary ?? {};
  return (
    <>
      <section className="card" aria-labelledby="rp-h">
        <h2 id="rp-h">Timeline</h2>
        <TimelineChart timeline={timeline} cursor={cursor} />
        <div className="toolbar" style={{ marginTop: 12 }}>
          <button type="button" onClick={() => setCursor(Math.max(0, cursor - 1))} disabled={cursor === 0}>
            Step back
          </button>
          <label className="field" style={{ flex: 1, minWidth: 220 }}>
            Replay time
            <input
              type="range"
              min={0}
              max={last}
              value={cursor}
              onChange={(e) => setCursor(Number(e.target.value))}
              aria-valuetext={when}
              style={{ padding: 0 }}
            />
          </label>
          <button type="button" onClick={() => setCursor(Math.min(last, cursor + 1))} disabled={cursor >= last}>
            Step forward
          </button>
        </div>
        <p aria-live="polite" data-testid="replay-status">
          At <strong>{when}</strong> UTC: {formatNumber(eventsBy(doc, cursor))} of {formatNumber(Number(s.n_test_events ?? 0))} test
          transfers seen, <strong>{seen.length}</strong> of {doc.events.length} flagged rings detectable.
        </p>
      </section>

      <section className="card" aria-labelledby="det-h">
        <h2 id="det-h">Rings detected so far</h2>
        {seen.length === 0 ? (
          <p className="muted">None yet. Move the replay time forward.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Ring</th>
                  <th scope="col" className="num">Rank</th>
                  <th scope="col" className="num">Score</th>
                  <th scope="col">First transfer</th>
                  <th scope="col">Detectable from</th>
                  <th scope="col" className="num">Time to assemble</th>
                  <th scope="col" className="num">Detection latency vs truth</th>
                </tr>
              </thead>
              <tbody>
                {seen.map((e) => (
                  <tr key={e.ring_id}>
                    <td className="mono">{e.ring_id}</td>
                    <td className="num">{e.rank}</td>
                    <td className="num">{formatScore(e.score)}</td>
                    <td>{formatTimestamp(e.first_ts)}</td>
                    <td>
                      {formatTimestamp(e.detected_ts)}
                      {e.partial && <span className="chip held" style={{ marginLeft: 6 }} title="The export kept too few transfers to reach the size limit">partial</span>}
                    </td>
                    <td className="num">{formatMinutes(e.assembly_minutes)}</td>
                    <td className="num">{e.latency_minutes == null ? "n/a" : formatMinutes(e.latency_minutes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card soft" aria-labelledby="sum-h">
        <h2 id="sum-h">Summary over all {doc.events.length} replayed rings</h2>
        <div className="grid cols-4">
          <div className="stat">
            <div className="label">Median time to assemble</div>
            <div className="value">{formatMinutes(s.assembly_minutes_median)}</div>
          </div>
          <div className="stat">
            <div className="label">90th percentile</div>
            <div className="value">{formatMinutes(s.assembly_minutes_p90)}</div>
          </div>
          <div className="stat">
            <div className="label">Median latency vs truth</div>
            <div className="value">{formatMinutes(s.latency_minutes_median)}</div>
          </div>
          <div className="stat">
            <div className="label">Rings with a truth match</div>
            <div className="value">{formatNumber(s.n_with_truth)}</div>
          </div>
        </div>
        <p className="small muted">
          Threshold {formatScore(doc.threshold ?? null)}; a ring is detected when its transfers touch {doc.min_ring_members ?? "?"}{" "}
          accounts. Expected values: {doc.events.length ? formatInr(doc.events.reduce((a, e) => a + (e.expected_value_inr ?? 0), 0)) : "n/a"} in
          total.
        </p>
        {doc.notes && (
          <ul className="small muted">
            {doc.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
