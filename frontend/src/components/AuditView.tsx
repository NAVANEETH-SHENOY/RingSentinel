"use client";
import { useState } from "react";
import { EmptyState, Loading } from "./DataState";
import { HttpError } from "@/lib/http";
import { formatTimestamp, shortHash } from "@/lib/format";
import { useSource } from "@/lib/SourceContext";
import { useResource } from "@/lib/useResource";
import { readToken, writeToken } from "@/lib/token";
import type { AuditEntry, VerifyResult } from "@/lib/types";

type Phase =
  | { kind: "no-api" }
  | { kind: "offline"; message: string }
  | { kind: "ready"; verify: VerifyResult };

type ListState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ok"; entries: AuditEntry[]; total: number }
  | { kind: "error"; message: string };

export function AuditView() {
  const source = useSource();
  const { state, reload } = useResource<Phase>(async () => {
    if (!source.config.apiBase) return { kind: "no-api" };
    try {
      return { kind: "ready", verify: await source.verify() };
    } catch (err) {
      return { kind: "offline", message: (err as Error).message };
    }
  }, [source]);
  const [token, setToken] = useState(() => readToken());
  const [remember, setRemember] = useState(() => readToken() !== "");
  const [list, setList] = useState<ListState>({ kind: "idle" });
  const phase: Phase | { kind: "loading" } = state.phase === "ready" ? state.value : { kind: "loading" };

  async function loadList(t: string) {
    setList({ kind: "loading" });
    try {
      const r = await source.audit(t.trim());
      setList({ kind: "ok", entries: r.entries, total: r.total });
      writeToken(remember ? t.trim() : null);
    } catch (err) {
      const status = err instanceof HttpError ? err.status : null;
      const message =
        status === 401 ? "The analyst token was not accepted."
        : status === 503 ? "The server has no analyst token configured (RS_ANALYST_TOKEN), so the audit list is switched off."
        : status === 429 ? "Too many requests. Wait a minute and try again."
        : `Could not load the audit log: ${(err as Error).message}`;
      setList({ kind: "error", message });
    }
  }

  return (
    <>
      <h1>Audit log</h1>
      <p className="muted">Every analyst action is appended to a log where each entry stores the hash of the one before it. It detects tampering; it does not prevent it, and it does not prove who acted (one shared token, free-text names).</p>
      {phase.kind === "loading" && <Loading label="Checking the audit chain" />}
      {phase.kind === "no-api" && (
        <EmptyState title="The audit log needs the backend">
          This interface is running in snapshot-only mode. Snapshots contain no analyst decisions. Set <span className="mono">NEXT_PUBLIC_API_BASE_URL</span> and start the API to see the log.
        </EmptyState>
      )}
      {phase.kind === "offline" && (
        <div className="state error" role="alert">
          <h3>Backend unreachable</h3>
          <p>{phase.message}</p>
          <p className="small muted">The queue, cases and metrics still work from the saved snapshot. The audit log lives only in the backend.</p>
          <button type="button" onClick={() => reload()}>Try again</button>
        </div>
      )}
      {phase.kind === "ready" && (
        <>
          <section className={`card ${phase.verify.ok ? "" : "soft"}`} aria-labelledby="chain-h" data-testid="chain-status">
            <h2 id="chain-h">Chain check</h2>
            {phase.verify.ok ? (
              <p>
                <span className="chip live">chain intact</span> {phase.verify.entries} entr{phase.verify.entries === 1 ? "y" : "ies"} checked. Head hash <span className="mono">{shortHash(phase.verify.head_hash, 16)}</span>. Note it somewhere else to make cut-off entries detectable.
              </p>
            ) : (
              <p role="alert">
                <span className="chip confirmed">chain broken</span> First bad entry: #{phase.verify.first_bad_seq ?? "?"}. {phase.verify.reason ?? ""} Treat this as tampering and restore from a trusted copy.
              </p>
            )}
          </section>

          <section className="card" aria-labelledby="entries-h">
            <h2 id="entries-h">Entries</h2>
            <form
              className="toolbar"
              onSubmit={(e) => {
                e.preventDefault();
                if (token.trim()) void loadList(token);
              }}
            >
              <label className="field">
                Analyst token
                <input type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} placeholder="RS_ANALYST_TOKEN" />
              </label>
              <label className="field" style={{ gridAutoFlow: "column", alignItems: "center", gap: 8 }}>
                <input type="checkbox" checked={remember} onChange={(e) => { setRemember(e.target.checked); if (!e.target.checked) writeToken(null); }} style={{ minWidth: 0 }} />
                Keep for this browser tab
              </label>
              <button type="submit" className="primary" disabled={!token.trim()}>Show entries</button>
            </form>
            {list.kind === "idle" && <p className="muted small">The list needs the analyst token. The token is sent only to the backend and is never written into the page.</p>}
            {list.kind === "loading" && <Loading label="Loading entries" />}
            {list.kind === "error" && <p role="alert" className="chip confirmed">{list.message}</p>}
            {list.kind === "ok" && (list.entries.length === 0 ? (
              <EmptyState title="No actions recorded yet" />
            ) : (
              <>
                <p className="small muted">Newest first. Showing {list.entries.length} of {list.total}.</p>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr><th scope="col" className="num">#</th><th scope="col">Time (UTC)</th><th scope="col">Ring</th><th scope="col">Action</th><th scope="col">Analyst</th><th scope="col">Note</th><th scope="col">Hash</th></tr>
                    </thead>
                    <tbody>
                      {list.entries.map((e) => (
                        <tr key={e.seq}>
                          <td className="num">{e.seq}</td>
                          <td>{formatTimestamp(e.ts)}</td>
                          <td className="mono">{e.ring_id}</td>
                          <td><span className={`chip ${e.action === "confirm" ? "confirmed" : e.action === "hold" ? "held" : "dismissed"}`}>{e.action}</span></td>
                          <td>{e.analyst}</td>
                          <td>{e.note}</td>
                          <td className="mono" title={e.hash}>{shortHash(e.hash)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ))}
          </section>
        </>
      )}
    </>
  );
}
