"use client";
import Link from "next/link";
import { EmptyState, ErrorState, Loading, OriginNote } from "./DataState";
import { ForceGraph } from "./ForceGraph";
import { StatusChip } from "./StatusChip";
import { formatInr, formatNumber, formatScore, formatTimestamp, humanizeKey } from "@/lib/format";
import { HttpError } from "@/lib/http";
import { useSource } from "@/lib/SourceContext";
import { useResource } from "@/lib/useResource";
import type { Case } from "@/lib/types";

const EDGE_ROWS = 50;

export function CaseView({ ringId }: { ringId: string | null }) {
  const source = useSource();
  const { state, reload } = useResource(
    async () => (ringId ? source.case(ringId) : null),
    [source, ringId],
  );

  if (!ringId) {
    return (
      <EmptyState title="No ring selected">
        Choose a ring from the <Link href="/">review queue</Link>.
      </EmptyState>
    );
  }
  if (state.phase === "loading") return <Loading label="Loading the case" />;
  if (state.phase === "error") {
    if (state.error instanceof HttpError && state.error.status === 404) {
      return (
        <EmptyState title="Ring not found">
          <span className="mono">{ringId}</span> is not in this snapshot. Go back to the <Link href="/">review queue</Link>.
        </EmptyState>
      );
    }
    return <ErrorState error={state.error} onRetry={reload} />;
  }
  const loaded = state.value;
  if (!loaded) return null;
  const c = loaded.data;
  return (
    <>
      <p className="small">
        <Link href="/">← Review queue</Link>
      </p>
      <h1>
        <span className="mono">{c.ring_id}</span> <StatusChip status={loaded.origin === "api" ? (c.status ?? "pending") : undefined} />
      </h1>
      <p className="muted">
        Rank {c.rank} in the queue{c.oversized ? " · oversized ring (could not be split below the size cap)" : ""}
        {loaded.origin === "api" && typeof c.n_actions === "number" ? ` · ${c.n_actions} analyst action(s) on record` : ""}
      </p>
      <OriginNote loaded={loaded} />

      <div className="grid cols-4" style={{ margin: "16px 0 20px" }}>
        <Stat label="Score (uncalibrated)" value={formatScore(c.score)} />
        <Stat label="Expected value (ranking heuristic)" value={formatInr(c.expected_value_inr)} />
        <Stat label="Accounts" value={formatNumber(c.n_members)} />
        <Stat label="Transfers" value={formatNumber(c.n_transfers)} />
        <Stat label="Amount moved" value={formatInr(c.amount_inr)} />
      </div>

      <section className="card" aria-labelledby="graph-h">
        <h2 id="graph-h">Transfer graph</h2>
        <ForceGraph ring={c} />
      </section>

      <div className="grid cols-2">
        <FeaturesCard c={c} />
        <AiCard c={c} />
      </div>

      <section className="card" aria-labelledby="edges-h">
        <h2 id="edges-h">Largest transfer links</h2>
        {c.edges.length === 0 ? (
          <p className="muted">No edges in this bundle.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">From</th>
                  <th scope="col">To</th>
                  <th scope="col" className="num">Transfers</th>
                  <th scope="col" className="num">Total</th>
                  <th scope="col">First</th>
                  <th scope="col">Last</th>
                </tr>
              </thead>
              <tbody>
                {c.edges.slice(0, EDGE_ROWS).map((e) => (
                  <tr key={`${e.src}>${e.dst}`}>
                    <td className="mono">{e.src}</td>
                    <td className="mono">{e.dst}</td>
                    <td className="num">{e.n_transfers}</td>
                    <td className="num">{formatInr(e.total_inr)}</td>
                    <td>{formatTimestamp(e.first_ts)}</td>
                    <td>{formatTimestamp(e.last_ts)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {c.edges.length > EDGE_ROWS && <p className="small muted">Showing the {EDGE_ROWS} largest of {c.edges.length} links.</p>}
      </section>

      <section className="card" aria-labelledby="members-h">
        <h2 id="members-h">Member accounts ({c.members.length}{c.members_truncated ? ` of ${c.n_members}` : ""})</h2>
        <p className="mono small" style={{ wordBreak: "break-all" }}>{c.members.join(", ")}</p>
        {c.members_truncated && <p className="small muted">The bundle keeps at most 500 member accounts per ring.</p>}
      </section>
    </>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
    </div>
  );
}

function FeaturesCard({ c }: { c: Case }) {
  const max = Math.max(...c.top_features.map((f) => Math.abs(f.mean_contribution)), 1e-9);
  return (
    <section className="card" aria-labelledby="feat-h">
      <h2 id="feat-h">Why it was flagged</h2>
      {c.top_features.length === 0 ? (
        <p className="muted">No feature contributions in this bundle.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th scope="col">Signal</th>
              <th scope="col" className="num">Mean contribution</th>
              <th scope="col" aria-hidden="true" style={{ width: "30%" }} />
            </tr>
          </thead>
          <tbody>
            {c.top_features.map((f) => (
              <tr key={f.feature}>
                <td>{humanizeKey(f.feature)}</td>
                <td className="num">{f.mean_contribution.toFixed(3)}</td>
                <td aria-hidden="true">
                  <div className="bar" style={{ width: `${Math.max(4, (Math.abs(f.mean_contribution) / max) * 100)}%` }} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="small muted">Contributions come from the model, not from a language model.</p>
    </section>
  );
}

function AiCard({ c }: { c: Case }) {
  return (
    <section className="card" aria-labelledby="ai-h">
      <h2 id="ai-h">Explanation</h2>
      {c.ai.status === "not_built" ? (
        <EmptyState title="No case file yet">
          The investigator, verifier and benign-explanation pass arrive in Stage {c.ai.built_in_stage}. Nothing on this page was written by a language model.
        </EmptyState>
      ) : (
        <p className="muted">An AI case file exists in this bundle, but this version of the interface does not display it yet (Stage 06).</p>
      )}
    </section>
  );
}
