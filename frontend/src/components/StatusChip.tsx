import type { Origin, RingStatus } from "@/lib/types";

export function StatusChip({ status }: { status: RingStatus | undefined }) {
  if (!status) return <span className="chip" title="Analyst decisions are only known when the API is on">not tracked</span>;
  return <span className={`chip ${status}`}>{status}</span>;
}

const ORIGIN_TEXT: Record<Origin, string> = { api: "Live API", snapshot: "Snapshot", demo: "Demo data" };
const ORIGIN_CLASS: Record<Origin, string> = { api: "live", snapshot: "snapshot", demo: "demo" };

export function OriginChip({ origin }: { origin: Origin }) {
  return <span className={`chip ${ORIGIN_CLASS[origin]}`}>{ORIGIN_TEXT[origin]}</span>;
}
