/** Where data comes from. Order: API (if configured) -> real snapshot -> demo snapshot.
 *  Every result says which source answered, so the UI never shows stale data as live. */

import { API_PREFIX, DEMO_PATH, SNAPSHOT_PATH, type RuntimeConfig, config as defaultConfig } from "./config";
import { getJson, HttpError } from "./http";
import {
  SUPPORTED_SCHEMA_VERSION,
  type AuditEntry,
  type Case,
  type Health,
  type Loaded,
  type Meta,
  type MetricsDoc,
  type Origin,
  type Placeholder,
  type Queue,
  type VerifyResult,
} from "./types";

export class DataUnavailableError extends Error {
  constructor(
    message: string,
    public readonly causes: string[],
  ) {
    super(message);
    this.name = "DataUnavailableError";
  }
}

export class SchemaVersionError extends Error {
  constructor(found: unknown) {
    super(`Unsupported snapshot schema_version ${String(found)} (this UI reads ${SUPPORTED_SCHEMA_VERSION}).`);
    this.name = "SchemaVersionError";
  }
}

function checkVersion<T extends { schema_version?: string }>(doc: T): T {
  if (doc.schema_version !== SUPPORTED_SCHEMA_VERSION) throw new SchemaVersionError(doc.schema_version);
  return doc;
}

export interface Source {
  readonly config: RuntimeConfig;
  queue(): Promise<Loaded<Queue>>;
  case(ringId: string): Promise<Loaded<Case>>;
  metrics(): Promise<Loaded<MetricsDoc>>;
  meta(): Promise<Loaded<Meta>>;
  drift(): Promise<Loaded<Placeholder>>;
  replay(): Promise<Loaded<Placeholder>>;
  health(): Promise<Health | null>;
  verify(): Promise<VerifyResult>;
  audit(token: string, limit?: number): Promise<{ total: number; entries: AuditEntry[] }>;
}

export function createSource(cfg: RuntimeConfig = defaultConfig): Source {
  const apiUrl = (path: string) => `${cfg.apiBase}${API_PREFIX}${path}`;
  const hasApi = cfg.apiBase !== "";
  let casesCache: Promise<{ doc: Record<string, Case>; origin: Origin; reason?: string }> | null = null;

  /** Try the API, then the real snapshot, then the demo snapshot. */
  async function tiered<T>(
    fromApi: (() => Promise<T>) | null,
    file: string,
    fromFile: (doc: unknown) => T,
  ): Promise<Loaded<T>> {
    const causes: string[] = [];
    if (hasApi && fromApi) {
      try {
        return { data: await fromApi(), origin: "api" };
      } catch (err) {
        if (err instanceof SchemaVersionError) throw err;
        causes.push(`API: ${(err as Error).message}`);
      }
    }
    for (const [origin, base] of [
      ["snapshot", SNAPSHOT_PATH],
      ["demo", DEMO_PATH],
    ] as const) {
      try {
        const doc = await getJson<unknown>(`${base}/${file}`, { timeoutMs: Math.max(cfg.timeoutMs, 8000) });
        const data = fromFile(doc);
        return { data, origin, fallbackReason: causes.length ? causes.join("; ") : undefined };
      } catch (err) {
        if (err instanceof SchemaVersionError) throw err;
        causes.push(`${origin}: ${(err as Error).message}`);
      }
    }
    throw new DataUnavailableError("No data source answered.", causes);
  }

  const source: Source = {
    config: cfg,

    queue: () =>
      tiered<Queue>(
        async () => {
          const doc = await getJson<Queue & { total?: number }>(apiUrl("/queue?limit=500"), { timeoutMs: cfg.timeoutMs });
          return checkVersion(doc);
        },
        "queue.json",
        (doc) => checkVersion(doc as Queue),
      ),

    async case(ringId) {
      const causes: string[] = [];
      if (hasApi) {
        try {
          const doc = await getJson<Case>(apiUrl(`/cases/${encodeURIComponent(ringId)}`), { timeoutMs: cfg.timeoutMs });
          return { data: doc, origin: "api" };
        } catch (err) {
          // 404 from a live API is an answer, not an outage.
          if (err instanceof HttpError && err.status === 404) throw err;
          causes.push(`API: ${(err as Error).message}`);
        }
      }
      if (!casesCache) {
        casesCache = tiered<Record<string, Case>>(null, "cases.json", (doc) => {
          const d = checkVersion(doc as { schema_version: string; cases: Record<string, Case> });
          return d.cases;
        }).then((r) => ({ doc: r.data, origin: r.origin, reason: r.fallbackReason }));
        casesCache.catch(() => {
          casesCache = null; // allow a later retry
        });
      }
      const { doc, origin, reason } = await casesCache;
      const found = doc[ringId];
      if (!found) throw new HttpError("no such ring in this snapshot", 404);
      const why = [...causes, ...(reason ? [reason] : [])].join("; ");
      return { data: found, origin, fallbackReason: why || undefined };
    },

    metrics: () =>
      tiered<MetricsDoc>(
        async () => checkVersion(await getJson<MetricsDoc>(apiUrl("/metrics"), { timeoutMs: cfg.timeoutMs })),
        "metrics.json",
        (doc) => checkVersion(doc as MetricsDoc),
      ),

    meta: () => tiered<Meta>(null, "meta.json", (doc) => checkVersion(doc as Meta)),

    drift: () =>
      tiered<Placeholder>(
        async () => checkVersion(await getJson<Placeholder>(apiUrl("/drift"), { timeoutMs: cfg.timeoutMs })),
        "drift.json",
        (doc) => checkVersion(doc as Placeholder),
      ),

    replay: () =>
      tiered<Placeholder>(
        async () => checkVersion(await getJson<Placeholder>(apiUrl("/replay"), { timeoutMs: cfg.timeoutMs })),
        "replay.json",
        (doc) => checkVersion(doc as Placeholder),
      ),

    async health() {
      if (!hasApi) return null;
      try {
        return await getJson<Health>(apiUrl("/health"), { timeoutMs: cfg.timeoutMs });
      } catch {
        return null;
      }
    },

    async verify() {
      if (!hasApi) throw new HttpError("no API configured", null);
      return getJson<VerifyResult>(apiUrl("/audit/verify"), { timeoutMs: cfg.timeoutMs });
    },

    async audit(token, limit = 100) {
      if (!hasApi) throw new HttpError("no API configured", null);
      return getJson<{ total: number; entries: AuditEntry[] }>(apiUrl(`/audit?limit=${limit}`), {
        timeoutMs: cfg.timeoutMs,
        headers: { "X-Analyst-Token": token },
      });
    },
  };
  return source;
}
