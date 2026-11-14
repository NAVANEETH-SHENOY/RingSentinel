"use client";
import { createContext, useContext, useMemo, type ReactNode } from "react";
import { createSource, type Source } from "./source";

const SourceContext = createContext<Source | null>(null);

export function SourceProvider({ source, children }: { source?: Source; children: ReactNode }) {
  const value = useMemo(() => source ?? createSource(), [source]);
  return <SourceContext.Provider value={value}>{children}</SourceContext.Provider>;
}

export function useSource(): Source {
  const s = useContext(SourceContext);
  if (!s) throw new Error("useSource must be used inside <SourceProvider>");
  return s;
}
