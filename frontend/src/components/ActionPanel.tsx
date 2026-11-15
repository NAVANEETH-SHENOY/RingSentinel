"use client";
import { useRef, useState } from "react";
import { HttpError } from "@/lib/http";
import { newIdempotencyKey } from "@/lib/idempotency";
import { useSource } from "@/lib/SourceContext";
import { readToken, writeToken } from "@/lib/token";
import type { AnalystAction, RingStatus } from "@/lib/types";

const LABEL: Record<AnalystAction, string> = { confirm: "Confirm ring", dismiss: "Dismiss", hold: "Hold" };
const HELP: Record<AnalystAction, string> = {
  confirm: "The ring is real abuse. Recorded in the audit log. The case is closed.",
  dismiss: "A false alarm. Closes the case and nudges the review threshold up a little (bounded).",
  hold: "Not sure yet. Keeps the case open and changes nothing else.",
};

/** Which actions the backend will accept from each status (mirrors backend/app/audit.py). */
export function allowedActions(status: RingStatus): AnalystAction[] {
  if (status === "pending") return ["confirm", "dismiss", "hold"];
  if (status === "held") return ["confirm", "dismiss"];
  return [];
}

function explain(err: unknown): string {
  if (!(err instanceof HttpError)) return `Could not record the decision: ${(err as Error).message}`;
  switch (err.status) {
    case 401:
      return "The analyst token was not accepted.";
    case 503:
      return "The server has no analyst token configured (RS_ANALYST_TOKEN), so decisions are switched off.";
    case 409:
      return `The server refused this decision: ${err.message}`;
    case 422:
      return `The server rejected the form: ${err.message}`;
    case 429:
      return "Too many requests. Wait a minute and try again.";
    case 404:
      return "The live backend does not know this ring (it may serve a different bundle).";
    case null:
      return `The backend could not be reached, so nothing was recorded. You can press the same button again: it is safe to retry. (${err.message})`;
    default:
      return `Could not record the decision: ${err.message}`;
  }
}

export function ActionPanel(props: {
  ringId: string;
  status: RingStatus;
  /** True only when this case was just read from the live API. */
  live: boolean;
  onDecided: () => void;
}) {
  const source = useSource();
  const [analyst, setAnalyst] = useState("");
  const [note, setNote] = useState("");
  const [token, setToken] = useState(() => readToken());
  const [remember, setRemember] = useState(() => readToken() !== "");
  const [busy, setBusy] = useState<AnalystAction | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  // One key per (action, form contents): a retry after a network failure reuses it.
  const pending = useRef<{ signature: string; key: string } | null>(null);

  if (!source.config.apiBase) {
    return (
      <section className="card soft" aria-labelledby="act-h">
        <h2 id="act-h">Decision</h2>
        <p className="muted">
          Decisions are recorded by the backend. This interface is running from snapshots only, so there is nothing to
          record against.
        </p>
      </section>
    );
  }
  const allowed = allowedActions(props.status);
  const closed = allowed.length === 0;
  const formOk = analyst.trim() !== "" && token.trim().length >= 16;

  async function submit(action: AnalystAction) {
    const signature = JSON.stringify([props.ringId, action, analyst.trim(), note.trim()]);
    if (pending.current?.signature !== signature) pending.current = { signature, key: newIdempotencyKey() };
    setBusy(action);
    setMessage(null);
    try {
      const out = await source.act(
        props.ringId,
        { action, analyst: analyst.trim(), note: note.trim(), idempotency_key: pending.current.key },
        token.trim(),
      );
      pending.current = null;
      writeToken(remember ? token.trim() : null);
      setNote("");
      setMessage({
        kind: "ok",
        text: out.replayed
          ? `Already recorded as "${out.status}" (this was a repeat of an earlier request).`
          : `Recorded: ${out.status}. Audit entry #${out.entry.seq}.`,
      });
      props.onDecided();
    } catch (err) {
      setMessage({ kind: "error", text: explain(err) });
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="card" aria-labelledby="act-h" data-testid="action-panel">
      <h2 id="act-h">Decision</h2>
      {!props.live && (
        <p className="small muted" role="note">
          This case was read from a saved snapshot, not the live backend, so its status may be out of date. Reload once the
          backend is back before deciding.
        </p>
      )}
      {closed ? (
        <p>
          This ring is already <strong>{props.status}</strong>. A decided case is closed; the audit log keeps the record.
        </p>
      ) : (
        <>
          <div className="toolbar">
            <label className="field">
              Your name
              <input value={analyst} onChange={(e) => setAnalyst(e.target.value)} maxLength={64} autoComplete="off" />
            </label>
            <label className="field">
              Analyst token
              <input type="password" value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" />
            </label>
            <label className="field" style={{ flex: 1, minWidth: 220 }}>
              Note (optional)
              <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
            </label>
          </div>
          <label className="small">
            <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> Remember the token for this
            tab only
          </label>
          <div className="toolbar" style={{ marginTop: 12 }}>
            {allowed.map((a) => (
              <button
                key={a}
                type="button"
                className={a === "confirm" ? "primary" : undefined}
                disabled={!formOk || busy !== null}
                title={HELP[a]}
                onClick={() => void submit(a)}
              >
                {busy === a ? "Saving…" : LABEL[a]}
              </button>
            ))}
          </div>
          <ul className="small muted" style={{ paddingLeft: 18 }}>
            {allowed.map((a) => (
              <li key={a}>
                <strong>{LABEL[a]}:</strong> {HELP[a]}
              </li>
            ))}
          </ul>
          {!formOk && <p className="small muted">Enter your name and the analyst token (at least 16 characters) to enable the buttons.</p>}
        </>
      )}
      <div aria-live="polite">
        {message && (
          <p className={message.kind === "error" ? "small" : "small"} role={message.kind === "error" ? "alert" : "status"} data-testid="action-message">
            {message.text}
          </p>
        )}
      </div>
    </section>
  );
}
