"use client";
import { EmptyState, OriginNote, Resource } from "./DataState";
import { DriftChart } from "./monitorCharts";
import { formatNumber, formatPercent, formatScore, formatTimestamp } from "@/lib/format";
import { useSource } from "@/lib/SourceContext";
import { useResource } from "@/lib/useResource";
import type { DriftDoc } from "@/lib/types";

export function DriftView() {
  const source = useSource();
  const { state, reload } = useResource(() => source.drift(), [source]);
  return (
    <>
      <h1>Drift</h1>
      <p className="muted">
        Has the score distribution moved away from what the detector was validated on? PSI compares each time window of the
        test period with the validation scores. It is a warning light, not a verdict.
      </p>
      <Resource state={state} onRetry={reload} loadingLabel="Loading drift">
        {(loaded) => (
          <>
            <OriginNote loaded={loaded} />
            <DriftBody doc={loaded.data} />
          </>
        )}
      </Resource>
    </>
  );
}

function DriftBody({ doc }: { doc: DriftDoc }) {
  if (doc.status !== "ready" || !doc.summary || doc.psi_warn_level == null || doc.psi_alert_level == null) {
    return (
      <EmptyState title="Drift was not computed for this bundle">
        It needs the scored events from the detection stage. Re-run the export with scores and events present.
      </EmptyState>
    );
  }
  const s = doc.summary;
  const alerting = s.n_alert > 0;
  return (
    <>
      <div className={`card ${alerting ? "" : "soft"}`} role={alerting ? "alert" : "status"} data-testid="drift-status">
        {alerting ? (
          <p>
            <span className="chip confirmed">drift alert</span> {s.n_alert} of {s.n_windows} windows are above the alert level{" "}
            {doc.psi_alert_level}; the first is window {(s.first_alert_index ?? 0) + 1}. Review the detector before trusting new
            flags, and look at the precision column below.
          </p>
        ) : s.n_warn > 0 ? (
          <p>
            <span className="chip held">drifting</span> {s.n_warn} window(s) are above the warn level {doc.psi_warn_level}, none
            above the alert level.
          </p>
        ) : (
          <p>
            <span className="chip live">stable</span> No window is above the warn level {doc.psi_warn_level}. Largest PSI{" "}
            {formatNumber(s.max_psi)}.
          </p>
        )}
      </div>

      <section className="card" aria-labelledby="psi-h">
        <h2 id="psi-h">PSI by time window</h2>
        <DriftChart windows={doc.windows} warn={doc.psi_warn_level} alert={doc.psi_alert_level} />
        <p className="small muted">
          Reference: {formatNumber(doc.reference?.n_events)} validation scores. Detector {doc.detector}. Whole test period PSI{" "}
          {formatNumber(s.test_psi)}.
        </p>
      </section>

      <section className="card" aria-labelledby="win-h">
        <h2 id="win-h">Windows</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Window</th>
                <th scope="col">From</th>
                <th scope="col" className="num">Events</th>
                <th scope="col" className="num">PSI</th>
                <th scope="col">Level</th>
                <th scope="col" className="num">Mean score</th>
                <th scope="col" className="num">Flagged</th>
                <th scope="col" className="num">Precision</th>
                <th scope="col" className="num">Recall</th>
              </tr>
            </thead>
            <tbody>
              {doc.windows.map((w) => (
                <tr key={w.index}>
                  <td>W{w.index + 1}</td>
                  <td>{formatTimestamp(w.start_ts)}</td>
                  <td className="num">{formatNumber(w.n_events)}</td>
                  <td className="num">{w.psi === null ? "n/a" : w.psi.toFixed(3)}</td>
                  <td>
                    <span className={`chip ${w.level === "alert" ? "confirmed" : w.level === "warn" ? "held" : ""}`}>{w.level}</span>
                  </td>
                  <td className="num">{formatScore(w.mean_score)}</td>
                  <td className="num">{formatPercent(w.flagged_rate)}</td>
                  <td className="num">{formatPercent(w.precision_at_threshold)}</td>
                  <td className="num">{formatPercent(w.recall_at_threshold)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
