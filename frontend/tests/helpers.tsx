import { render } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { ReactElement } from "react";
import { vi } from "vitest";
import { SourceProvider } from "@/lib/SourceContext";
import { createSource, type Source } from "@/lib/source";
import type { RuntimeConfig } from "@/lib/config";

const DEMO_DIR = join(__dirname, "..", "public", "demo-snapshots");

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function demoDoc<T extends object = Record<string, any>>(name: string): T {
  return JSON.parse(readFileSync(join(DEMO_DIR, name), "utf-8")) as T;
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

type Handler = (url: string, init?: RequestInit) => Response | Promise<Response>;

/** Install a fetch mock. The first route whose key is a substring of the URL answers; anything
 *  else rejects like a network failure. Returns the mock so tests can inspect calls. */
export function mockFetch(routes: Record<string, Handler>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    for (const [key, handler] of Object.entries(routes)) {
      if (url.includes(key)) return handler(url, init);
    }
    throw new TypeError(`network down: ${url}`);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

/** Serve the committed demo bundle as the static snapshot at /snapshots/. */
export function snapshotRoutes(base = "/snapshots"): Record<string, Handler> {
  const routes: Record<string, Handler> = {};
  for (const f of ["meta.json", "queue.json", "cases.json", "metrics.json", "drift.json", "replay.json"]) {
    routes[`${base}/${f}`] = () => jsonResponse(demoDoc(f));
  }
  return routes;
}

export const OFFLINE_CFG: RuntimeConfig = { apiBase: "", timeoutMs: 500 };
export const API_CFG: RuntimeConfig = { apiBase: "http://api.test", timeoutMs: 500 };

export function renderWith(ui: ReactElement, source: Source = createSource(OFFLINE_CFG)) {
  return render(<SourceProvider source={source}>{ui}</SourceProvider>);
}
