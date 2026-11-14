"use client";
import { useCallback, useEffect, useState } from "react";

export type ResourceState<T> =
  | { phase: "loading" }
  | { phase: "ready"; value: T }
  | { phase: "error"; error: Error };

function sameDeps(a: readonly unknown[], b: readonly unknown[]): boolean {
  return a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
}

/** Runs `load` on mount and whenever `deps` change; `reload()` runs it again.
 *  A change of `deps` resets the state to "loading" during render (React's documented way to
 *  adjust state when inputs change), so no stale value is ever shown for new inputs. */
export function useResource<T>(load: () => Promise<T>, deps: readonly unknown[]) {
  const [state, setState] = useState<ResourceState<T>>({ phase: "loading" });
  const [tick, setTick] = useState(0);
  const [seenDeps, setSeenDeps] = useState(deps);
  if (!sameDeps(seenDeps, deps)) {
    setSeenDeps(deps);
    setState({ phase: "loading" });
  }

  useEffect(() => {
    let cancelled = false;
    load().then(
      (value) => {
        if (!cancelled) setState({ phase: "ready", value });
      },
      (error: unknown) => {
        if (!cancelled) setState({ phase: "error", error: error instanceof Error ? error : new Error(String(error)) });
      },
    );
    return () => {
      cancelled = true;
    };
    // `load` is a fresh closure every render; the caller's `deps` say when to run again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const reload = useCallback(() => {
    setState({ phase: "loading" });
    setTick((t) => t + 1);
  }, []);
  return { state, reload };
}
