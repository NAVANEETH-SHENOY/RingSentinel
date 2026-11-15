import type { ReplayDoc, ReplayEvent } from "./types";

const toMs = (ts: string): number => Date.parse(`${ts}Z`);

/** Time at the end of step `index` (0-based), in the same ISO form as the document. */
export function stepEndMs(timeline: NonNullable<ReplayDoc["timeline"]>, index: number): number {
  const start = toMs(timeline.start_ts);
  const end = toMs(timeline.end_ts);
  if (!Number.isFinite(start) || !Number.isFinite(end) || timeline.n_steps <= 0) return start;
  return start + ((end - start) * (index + 1)) / timeline.n_steps;
}

/** Rings whose detection time is at or before the end of step `index`, in detection order. */
export function detectedBy(doc: ReplayDoc, index: number): ReplayEvent[] {
  if (!doc.timeline) return [];
  const limit = stepEndMs(doc.timeline, index);
  return doc.events.filter((e) => toMs(e.detected_ts) <= limit);
}

/** Test events seen up to and including step `index`. */
export function eventsBy(doc: ReplayDoc, index: number): number {
  if (!doc.timeline) return 0;
  return doc.timeline.events.slice(0, index + 1).reduce((a, b) => a + b, 0);
}

export function formatMinutes(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || !Number.isFinite(minutes)) return "n/a";
  if (minutes < 90) return `${Math.round(minutes)} min`;
  if (minutes < 60 * 48) return `${(minutes / 60).toFixed(1)} h`;
  return `${(minutes / 1440).toFixed(1)} days`;
}
