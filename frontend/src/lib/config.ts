/** Build-time configuration (NEXT_PUBLIC_* values are inlined by Next.js). */

export const API_PREFIX = "/api/v1";
export const SNAPSHOT_PATH = "/snapshots";
export const DEMO_PATH = "/demo-snapshots";
export const DEFAULT_TIMEOUT_MS = 4000;

export interface RuntimeConfig {
  /** Empty string = snapshot-only mode. */
  apiBase: string;
  timeoutMs: number;
}

export function readConfig(env: Record<string, string | undefined>): RuntimeConfig {
  const raw = (env.NEXT_PUBLIC_API_BASE_URL ?? "").trim().replace(/\/+$/, "");
  const parsed = Number.parseInt((env.NEXT_PUBLIC_API_TIMEOUT_MS ?? "").trim(), 10);
  const timeoutMs = Number.isFinite(parsed) && parsed >= 200 && parsed <= 60_000 ? parsed : DEFAULT_TIMEOUT_MS;
  return { apiBase: raw, timeoutMs };
}

// Next.js replaces each literal process.env.NEXT_PUBLIC_* access at build time, so they must be
// written out one by one (a dynamic lookup would not be inlined).
export const config: RuntimeConfig = readConfig({
  NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL,
  NEXT_PUBLIC_API_TIMEOUT_MS: process.env.NEXT_PUBLIC_API_TIMEOUT_MS,
});
