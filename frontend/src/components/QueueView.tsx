"use client";
import Link from "next/link";
import { useMemo, useState } from "react";
import { EmptyState, OriginNote, Resource } from "./DataState";
import { StatusChip } from "./StatusChip";
import { formatInr, formatScore } from "@/lib/format";
import { useSource } from "@/lib/SourceContext";
import { useResource } from "@/lib/useResource";
import type { QueueItem, RingStatus } from "@/lib/types";

const PAGE_SIZE = 25;
type StatusFilter = "all" | RingStatus;

export function QueueView() {
  const source = useSource();
  const { state, reload } = useResource(() => source.queue(), [source]);
  const [text, setText] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [page, setPage] = useState(0);

  return (
    <>
      <h1>Review queue</h1>
      <p className="muted">Rings ordered by expected value of a review. A human confirms, dismisses or holds each one; nothing is blocked automatically.</p>
      <Resource state={state} onRetry={reload} loadingLabel="Loading the review queue">
        {(loaded) => {
          const q = loaded.data;
          return (
            <QueueBody
              items={q.items}
              origin={loaded}
              header={q}
              text={text}
              setText={(v) => {
                setText(v);
                setPage(0);
              }}
              status={status}
              setStatus={(v) => {
                setStatus(v);
                setPage(0);
              }}
              page={page}
              setPage={setPage}
            />
          );
        }}
      </Resource>
    </>
  );
}

function QueueBody(props: {
  items: QueueItem[];
  origin: { origin: "api" | "snapshot" | "demo"; fallbackReason?: string };
  header: { value_formula: string; cost_assumptions: { review_cost_inr: number; fp_cost_inr: number; loss_capture_rate: number }; score_calibrated: false; threshold: number | null; threshold_kind: string; note?: string };
  text: string;
  setText: (v: string) => void;
  status: StatusFilter;
  setStatus: (v: StatusFilter) => void;
  page: number;
  setPage: (n: number) => void;
}) {
  const { items, origin, header, text, status, page } = props;
  const statusKnown = origin.origin === "api";
  const filtered = useMemo(() => {
    const t = text.trim().toLowerCase();
    return items.filter(
      (i) => (t === "" || i.ring_id.toLowerCase().includes(t)) && (status === "all" || (statusKnown && (i.status ?? "pending") === status)),
    );
  }, [items, text, status, statusKnown]);
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pages - 1);
  const rows = filtered.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE);

  return (
    <>
      <OriginNote loaded={origin} />
      <details className="card soft">
        <summary>How the order is computed</summary>
        <p className="small">{header.value_formula}</p>
        <p className="small muted">
          Costs used: review {formatInr(header.cost_assumptions.review_cost_inr)}, wrongly included account {formatInr(header.cost_assumptions.fp_cost_inr)}, capture rate{" "}
          {header.cost_assumptions.loss_capture_rate}. These are planning assumptions. The score is not a calibrated probability.
        </p>
        {header.note && <p className="small">{header.note}</p>}
      </details>

      {items.length === 0 ? (
        <EmptyState title="No rings to review">
          The detector flagged nothing at its validation threshold{header.note ? `: ${header.note}` : "."}
        </EmptyState>
      ) : (
        <>
          <div className="toolbar">
            <label className="field">
              Search ring id
              <input value={text} onChange={(e) => props.setText(e.target.value)} placeholder="R-3f2a…" />
            </label>
            <label className="field">
              Status
              <select
                value={status}
                onChange={(e) => props.setStatus(e.target.value as StatusFilter)}
                disabled={!statusKnown}
                title={statusKnown ? undefined : "Analyst decisions are only known when the API is on"}
              >
                <option value="all">All</option>
                <option value="pending">Pending</option>
                <option value="held">Held</option>
                <option value="confirmed">Confirmed</option>
                <option value="dismissed">Dismissed</option>
              </select>
            </label>
            <span className="small muted" aria-live="polite">
              {filtered.length} of {items.length} rings
            </span>
          </div>
          {filtered.length === 0 ? (
            <EmptyState title="No rings match these filters" />
          ) : (
            <div className="table-wrap">
              <table>
                <caption className="sr-only">Rings ordered by expected value</caption>
                <thead>
                  <tr>
                    <th scope="col">#</th>
                    <th scope="col">Ring</th>
                    <th scope="col" className="num">Score</th>
                    <th scope="col" className="num">Expected value</th>
                    <th scope="col" className="num">Accounts</th>
                    <th scope="col" className="num">Transfers</th>
                    <th scope="col" className="num">Amount</th>
                    <th scope="col">Top signals</th>
                    <th scope="col">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.ring_id}>
                      <td>{r.rank}</td>
                      <td>
                        <Link href={`/case/?id=${encodeURIComponent(r.ring_id)}`} className="mono">
                          {r.ring_id}
                        </Link>
                        {r.oversized && <span className="chip held" style={{ marginLeft: 6 }} title="Could not be split below the community size cap">oversized</span>}
                      </td>
                      <td className="num">{formatScore(r.score)}</td>
                      <td className="num">{formatInr(r.expected_value_inr)}</td>
                      <td className="num">{r.n_members}</td>
                      <td className="num">{r.n_transfers}</td>
                      <td className="num">{formatInr(r.amount_inr)}</td>
                      <td className="small">{r.top_features.map((f) => f.feature).join(", ") || "n/a"}</td>
                      <td>
                        <StatusChip status={statusKnown ? (r.status ?? "pending") : undefined} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {pages > 1 && (
            <div className="pager">
              <button type="button" onClick={() => props.setPage(safePage - 1)} disabled={safePage === 0}>
                Previous
              </button>
              <span className="small">
                Page {safePage + 1} of {pages}
              </span>
              <button type="button" onClick={() => props.setPage(safePage + 1)} disabled={safePage >= pages - 1}>
                Next
              </button>
            </div>
          )}
        </>
      )}
    </>
  );
}
