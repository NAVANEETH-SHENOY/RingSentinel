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

const SOURCE_TEXT: Record<string, string> = {
  llm: "Written by a language model",
  cache: "Written by a language model (cached)",
  template: "Rule-based summary, no language model",
};

function Level({ label, level }: { label: string; level: string }) {
  return (
    <span className="chip" data-testid={`ai-${label.toLowerCase()}`}>
      {label}: {level}
    </span>
  );
}

function AiCard({ c }: { c: Case }) {
  const ai = c.ai;
  if (ai.status !== "ready" || !ai.investigator) {
    return (
      <section className="card" aria-labelledby="ai-h">
        <h2 id="ai-h">Explanation</h2>
        <EmptyState title="No case file yet">
          {ai.status === "not_built"
            ? `The investigator, verifier and benign-explanation pass have not been run for this bundle (Stage ${ai.built_in_stage}). Nothing on this page was written by a language model.`
            : "This bundle has an AI block without a case file."}
        </EmptyState>
      </section>
    );
  }
  const file = ai.investigator;
  const benign = ai.benign_explanation;
  const verified = ai.verifier?.status === "verified";
  const fromModel = ai.source === "llm" || ai.source === "cache";
  return (
    <section className="card" aria-labelledby="ai-h">
      <h2 id="ai-h">Explanation</h2>
      <p className="small">
        <span className={`chip ${verified ? "live" : "demo"}`} data-testid="ai-verifier">
          {verified ? "Facts verified against the transfers" : "Not verified"}
        </span>{" "}
        <span className="chip" data-testid="ai-source">
          {SOURCE_TEXT[ai.source ?? "template"] ?? "Unknown source"}
        </span>{" "}
        {ai.contested ? (
          <span className="chip held" data-testid="ai-contested">
            Contested
          </span>
        ) : null}
      </p>
      <p className="small muted">
        {verified
          ? "Verified means every count, amount and account cited matches this ring's transfers. It does not mean the interpretation is right. "
          : "Some cited facts did not match the transfers; treat this text with care. "}
        {fromModel ? "This text does not change the score, the rank or any decision." : "This summary is built by fixed rules from the transfers."}
      </p>
      <p>
        <Level label="Pattern" level={file.pattern.replace(/_/g, " ")} /> <Level label="Suspicion" level={file.suspicion} />
      </p>
      <p>{file.summary}</p>
      <ul>
        {file.findings.map((f, i) => (
          <li key={i}>{f.text}</li>
        ))}
      </ul>
      {file.key_accounts && file.key_accounts.length > 0 ? (
        <>
          <h3>Key accounts</h3>
          <ul>
            {file.key_accounts.map((k, i) => (
              <li key={i}>
                <code>{k.account}</code> ({k.role}): {k.reason}
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {file.limits ? <p className="small muted">What this data cannot show: {file.limits}</p> : null}
      {file.suggested_checks && file.suggested_checks.length > 0 ? (
        <>
          <h3>Suggested checks</h3>
          <ul>
            {file.suggested_checks.map((t, i) => (
              <li key={i}>{t}</li>
            ))}
          </ul>
        </>
      ) : null}
      {benign ? (
        <>
          <h3>The innocent explanation</h3>
          <p className="small">
            <Level label="Plausibility" level={benign.plausibility} />
          </p>
          <p>{benign.summary}</p>
          <ul>
            {benign.hypotheses.map((h, i) => (
              <li key={i}>
                <strong>{h.label.replace(/_/g, " ")}</strong> ({h.strength}): {h.argument}
                {h.how_to_check ? <span className="muted"> How to check: {h.how_to_check}</span> : null}
              </li>
            ))}
          </ul>
          {benign.weakest_point ? <p className="small muted">Weakest point of this reading: {benign.weakest_point}</p> : null}
          {ai.contested && ai.contested_reason ? <p className="small">{ai.contested_reason}</p> : null}
        </>
      ) : null}
      {ai.verifier?.issues && ai.verifier.issues.length > 0 ? (
        <details>
          <summary>Verifier notes</summary>
          <ul>
            {ai.verifier.issues.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        </details>
      ) : null}
      {ai.provider ? (
        <p className="small muted">
          Source: {ai.provider.name} / {ai.provider.model}
        </p>
      ) : null}
    </section>
  );
}
