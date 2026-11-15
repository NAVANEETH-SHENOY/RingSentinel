import type { QueueItem } from "./types";

/** One-line description of where a ring stands in the live (feedback-adjusted) order. */
export function liveLabel(item: QueueItem): string {
  const status = item.status ?? "pending";
  if (status === "confirmed" || status === "dismissed") return "decided";
  if (!item.live) return "—";
  if (item.live.live_rank !== null) return `#${item.live.live_rank}`;
  return item.live.above_threshold ? "not worth a review" : "below threshold";
}

/** True when the API supplied live fields for at least one ring. */
export function hasLive(items: QueueItem[]): boolean {
  return items.some((i) => i.live !== undefined);
}
