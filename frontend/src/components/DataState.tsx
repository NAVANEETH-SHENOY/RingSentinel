"use client";
import type { ReactNode } from "react";
import { DataUnavailableError } from "@/lib/source";
import type { Loaded } from "@/lib/types";
import type { ResourceState } from "@/lib/useResource";

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="state" role="status" aria-live="polite">
      <div className="spinner" aria-hidden="true" />
      <p className="muted">{label}…</p>
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="state" role="status">
      <h3>{title}</h3>
      {children ? <div className="muted">{children}</div> : null}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  const causes = error instanceof DataUnavailableError ? error.causes : [];
  return (
    <div className="state error" role="alert">
      <h3>Could not load data</h3>
      <p>{error.message}</p>
      {causes.length > 0 && (
        <ul className="small muted" style={{ listStyle: "none", padding: 0 }}>
          {causes.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      )}
      <p className="small muted">
        Put a bundle in <span className="mono">frontend/public/snapshots</span> (see docs/STAGE_05.md) or start the API.
      </p>
      {onRetry && (
        <button type="button" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

/** Says where the data came from when it is not the live API, and why. */
export function OriginNote({ loaded }: { loaded: Pick<Loaded<unknown>, "origin" | "fallbackReason"> }) {
  if (loaded.origin === "api") return null;
  const text =
    loaded.origin === "demo"
      ? "Showing the built-in demo bundle (invented data for UI development)."
      : "Showing the saved snapshot, not live data.";
  return (
    <p className="small muted" data-testid="origin-note">
      {text}
      {loaded.fallbackReason ? ` Backend unavailable: ${loaded.fallbackReason}` : ""}
    </p>
  );
}

export function Resource<T>({
  state,
  onRetry,
  loadingLabel,
  children,
}: {
  state: ResourceState<T>;
  onRetry?: () => void;
  loadingLabel?: string;
  children: (value: T) => ReactNode;
}) {
  if (state.phase === "loading") return <Loading label={loadingLabel} />;
  if (state.phase === "error") return <ErrorState error={state.error} onRetry={onRetry} />;
  return <>{children(state.value)}</>;
}
