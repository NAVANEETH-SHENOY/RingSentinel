import { afterEach, describe, expect, it, vi } from "vitest";
import { DataUnavailableError, SchemaVersionError, createSource } from "@/lib/source";
import { readConfig } from "@/lib/config";
import { API_CFG, OFFLINE_CFG, demoDoc, jsonResponse, mockFetch, snapshotRoutes } from "./helpers";

afterEach(() => vi.unstubAllGlobals());

describe("readConfig", () => {
  it("defaults to snapshot-only mode and strips trailing slashes", () => {
    expect(readConfig({})).toEqual({ apiBase: "", timeoutMs: 4000 });
    expect(readConfig({ NEXT_PUBLIC_API_BASE_URL: " http://x:8000/// " }).apiBase).toBe("http://x:8000");
  });
  it("ignores a nonsense timeout", () => {
    expect(readConfig({ NEXT_PUBLIC_API_TIMEOUT_MS: "abc" }).timeoutMs).toBe(4000);
    expect(readConfig({ NEXT_PUBLIC_API_TIMEOUT_MS: "5" }).timeoutMs).toBe(4000);
    expect(readConfig({ NEXT_PUBLIC_API_TIMEOUT_MS: "1500" }).timeoutMs).toBe(1500);
  });
});

describe("createSource without an API", () => {
  it("reads the real snapshot and never calls the API", async () => {
    const f = mockFetch(snapshotRoutes("/snapshots"));
    const q = await createSource(OFFLINE_CFG).queue();
    expect(q.origin).toBe("snapshot");
    expect(q.data.items.length).toBeGreaterThan(5);
    expect(f.mock.calls.every(([u]) => String(u).startsWith("/snapshots/"))).toBe(true);
  });

  it("falls back to the demo bundle when there is no real snapshot", async () => {
    mockFetch({ "/snapshots/": () => jsonResponse({ detail: "nope" }, 404), ...snapshotRoutes("/demo-snapshots") });
    const q = await createSource(OFFLINE_CFG).queue();
    expect(q.origin).toBe("demo");
  });

  it("raises DataUnavailableError listing every failure when nothing answers", async () => {
    mockFetch({});
    const err = await createSource(OFFLINE_CFG).queue().catch((e) => e);
    expect(err).toBeInstanceOf(DataUnavailableError);
    expect(err.causes).toHaveLength(2);
  });

  it("refuses a bundle with an unknown schema version", async () => {
    mockFetch({ "/snapshots/queue.json": () => jsonResponse({ ...demoDoc("queue.json"), schema_version: "2" }) });
    await expect(createSource(OFFLINE_CFG).queue()).rejects.toBeInstanceOf(SchemaVersionError);
  });
});

describe("createSource with an API", () => {
  it("prefers the live API", async () => {
    mockFetch({ "http://api.test/api/v1/queue": () => jsonResponse({ ...demoDoc("queue.json"), total: 14 }) });
    const q = await createSource(API_CFG).queue();
    expect(q.origin).toBe("api");
    expect(q.fallbackReason).toBeUndefined();
  });

  it("falls back to the snapshot and says why when the API is down", async () => {
    mockFetch(snapshotRoutes("/snapshots"));
    const q = await createSource(API_CFG).queue();
    expect(q.origin).toBe("snapshot");
    expect(q.fallbackReason).toMatch(/API/);
  });

  it("falls back when the API answers 500 or is too slow", async () => {
    mockFetch({ "http://api.test": () => jsonResponse({ detail: "boom" }, 500), ...snapshotRoutes("/snapshots") });
    expect((await createSource(API_CFG).queue()).origin).toBe("snapshot");

    vi.useFakeTimers();
    mockFetch({
      "http://api.test": (_u, init) => new Promise((_res, rej) => init?.signal?.addEventListener("abort", () => rej(new DOMException("aborted", "AbortError")))),
      ...snapshotRoutes("/snapshots"),
    });
    const pending = createSource(API_CFG).queue();
    await vi.advanceTimersByTimeAsync(600);
    const q = await pending;
    vi.useRealTimers();
    expect(q.origin).toBe("snapshot");
    expect(q.fallbackReason).toMatch(/timed out/);
  });

  it("serves a case from the snapshot when the API is down, caching cases.json once", async () => {
    const f = mockFetch(snapshotRoutes("/snapshots"));
    const src = createSource(API_CFG);
    const ids = demoDoc("queue.json").items.map((i: { ring_id: string }) => i.ring_id) as string[];
    const a = await src.case(ids[0]!);
    const b = await src.case(ids[1]!);
    expect(a.origin).toBe("snapshot");
    expect(b.data.ring_id).toBe(ids[1]);
    expect(f.mock.calls.filter(([u]) => String(u).endsWith("cases.json"))).toHaveLength(1);
  });

  it("treats a 404 from the live API as an answer, not an outage", async () => {
    mockFetch({ "http://api.test/api/v1/cases/": () => jsonResponse({ detail: "no such ring" }, 404), ...snapshotRoutes("/snapshots") });
    await expect(createSource(API_CFG).case("R-000000000000")).rejects.toMatchObject({ status: 404 });
  });

  it("reports health as null instead of throwing when the API is down", async () => {
    mockFetch({});
    expect(await createSource(API_CFG).health()).toBeNull();
  });

  it("sends the token header for the audit list", async () => {
    const f = mockFetch({ "/api/v1/audit": () => jsonResponse({ total: 0, entries: [] }) });
    await createSource(API_CFG).audit("secret-token-123456");
    const init = f.mock.calls[0]?.[1] as RequestInit;
    expect((init.headers as Record<string, string>)["X-Analyst-Token"]).toBe("secret-token-123456");
  });
});
