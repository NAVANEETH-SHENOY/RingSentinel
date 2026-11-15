"use client";
import { formatScore } from "@/lib/format";
import type { FeedbackState } from "@/lib/types";

export function FeedbackCard({ state }: { state: FeedbackState }) {
  const moved = state.offset_logit > 0;
  return (
    <details className="card soft" data-testid="feedback-card" open={moved}>
      <summary>
        Analyst feedback: threshold {formatScore(state.effective_threshold)}
        {moved ? ` (base ${formatScore(state.base_threshold)})` : " (unchanged)"}
      </summary>
      <div className="grid cols-4" style={{ margin: "12px 0" }}>
        <div className="stat">
          <div className="label">Confirmed</div>
          <div className="value">{state.n_confirmed}</div>
        </div>
        <div className="stat">
          <div className="label">Dismissed</div>
          <div className="value">{state.n_dismissed}</div>
        </div>
        <div className="stat">
          <div className="label">Shift (log-odds)</div>
          <div className="value">
            {state.offset_logit.toFixed(2)} / {state.max_offset_logit.toFixed(2)}
          </div>
        </div>
        <div className="stat">
          <div className="label">Open rings above threshold</div>
          <div className="value">{state.n_active}</div>
        </div>
      </div>
      {state.at_bound && (
        <p className="small" role="status">
          <span className="chip held">at the limit</span> The shift has reached its upper bound; further dismissals change nothing.
        </p>
      )}
      <p className="small">{state.rule}</p>
      <p className="small muted">{state.note}</p>
    </details>
  );
}
