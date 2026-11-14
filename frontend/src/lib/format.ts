/** Display formatting. Indian digit grouping for rupees, because the cost model is in INR. */

const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const num = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 3 });

export function formatInr(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "n/a";
  const sign = value < 0 ? "-" : "";
  return `${sign}₹${inr.format(Math.abs(value))}`;
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "n/a";
  return num.format(value);
}

export function formatScore(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "n/a";
  return value.toFixed(3);
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "n/a";
  return `${(value * 100).toFixed(digits)}%`;
}

export function shortHash(hash: string | null | undefined, n = 8): string {
  return hash ? hash.slice(0, n) : "n/a";
}

/** "2022-09-01T10:00:00" -> "2022-09-01 10:00". Falls back to the raw string. */
export function formatTimestamp(ts: string): string {
  const match = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/.exec(ts);
  return match ? `${match[1]} ${match[2]}` : ts;
}

export function humanizeKey(key: string): string {
  return key.replace(/_/g, " ").replace(/\s+/g, " ").trim();
}
