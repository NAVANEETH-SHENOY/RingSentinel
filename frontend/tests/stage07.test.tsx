import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuditView } from "@/components/AuditView";
import { CaseView } from "@/components/CaseView";
import { DriftView } from "@/components/DriftView";
import { QueueView } from "@/components/QueueView";
import { ReplayView } from "@/components/ReplayView";
import { HttpError } from "@/lib/http";
import { newIdempotencyKey } from "@/lib/idempotency";
import { hasLive, liveLabel } from "@/lib/liveQueue";
import { detectedBy, eventsBy, formatMinutes, stepEndMs } from "@/lib/replayView";
import { createSource } from "@/lib/source";
import type { ReplayDoc } from "@/lib/types";
import { API_CFG, demoDoc, jsonResponse, mockFetch, renderWith, snapshotRoutes } from "./helpers";

vi.mock("next/navigation", () => ({ usePathname: () => "/", useSearchParams: () => new URLSearchParams() }));
afterEach(() => {
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
});

const queue = demoDoc("queue.json");
const cases = demoDoc("cases.json");
const drift = demoDoc("drift.json");
const replay = demoDoc<ReplayDoc>("replay.json");
const firstId: string = queue.items[0].ring_id;
const TOKEN = "analyst-token-123456";

function entry(seq: number, action: string, ringId = firstId) {
  return { seq, ts: "2026-11-13T05:00:00.000000Z", ring_id: ringId, action, analyst: "asha", note: "", idempotency_key: "k".repeat(16), prev_hash: "0".repeat(64), hash: "a".repeat(64) };
}

async function fillForm() {
  await userEvent.type(screen.getByLabelText(/your name/i), "asha");
  await userEvent.type(screen.getByLabelText(/analyst token/i), TOKEN);
}

describe("lib helpers", () => {
  it("makes idempotency keys the backend accepts, and different each time", () => {
    const a = newIdempotencyKey();
    const b = newIdempotencyKey();
    expect(a).toMatch(/^[A-Za-z0-9_-]{16,64}$/);
    expect(a).not.toBe(b);
  });

  it("describes where a ring stands in the live order", () => {
    const base = { ...queue.items[0] };
    expect(liveLabel({ ...base, status: "confirmed" })).toBe("decided");
    expect(liveLabel({ ...base })).toBe("—");
    expect(liveLabel({ ...base, live: { adjusted_score: 0.5, adjusted_expected_value_inr: 1, above_threshold: true, live_rank: 3 } })).toBe("#3");
    expect(liveLabel({ ...base, live: { adjusted_score: 0.5, adjusted_expected_value_inr: -1, above_threshold: true, live_rank: null } })).toBe("not worth a review");
    expect(liveLabel({ ...base, live: { adjusted_score: 0.1, adjusted_expected_value_inr: 1, above_threshold: false, live_rank: null } })).toBe("below threshold");
    expect(hasLive([base])).toBe(false);
  });

  it("replays deterministically: later steps only ever add rings", () => {
    const n = replay.timeline!.n_steps;
    let previous = 0;
    for (let i = 0; i < n; i += 1) {
      const count = detectedBy(replay, i).length;
      expect(count).toBeGreaterThanOrEqual(previous);
      previous = count;
    }
    expect(previous).toBe(replay.events.length);
    expect(detectedBy(replay, n - 1)).toEqual(detectedBy(replay, n - 1));
    expect(eventsBy(replay, n - 1)).toBe(replay.summary!.n_test_events);
    expect(stepEndMs(replay.timeline!, n - 1)).toBe(Date.parse(`${replay.timeline!.end_ts}Z`));
  });

  it("formats minutes in a readable unit", () => {
    expect(formatMinutes(null)).toBe("n/a");
    expect(formatMinutes(45)).toBe("45 min");
    expect(formatMinutes(180)).toBe("3.0 h");
    expect(formatMinutes(60 * 24 * 5)).toBe("5.0 days");
  });
});

describe("source: queue order and actions", () => {
  it("asks the API for the live order by default of the UI and for the export order otherwise", async () => {
    const f = mockFetch({ "http://api.test/api/v1/queue": () => jsonResponse({ ...queue, total: 14 }) });
    await createSource(API_CFG).queue("live");
    await createSource(API_CFG).queue();
    const urls = f.mock.calls.map(([u]) => String(u));
    expect(urls[0]).toContain("order=live");
    expect(urls[1]).toContain("order=export");
  });

  it("posts a decision with the token header and the JSON body", async () => {
    const f = mockFetch({ "/action": () => jsonResponse({ ring_id: firstId, status: "confirmed", replayed: false, entry: entry(1, "confirm") }, 201) });
    const body = { action: "confirm" as const, analyst: "asha", note: "n", idempotency_key: "k".repeat(20) };
    const out = await createSource(API_CFG).act(firstId, body, TOKEN);
    expect(out.status).toBe("confirmed");
    const [url, init] = f.mock.calls[0]!;
    expect(String(url)).toContain(`/cases/${firstId}/action`);
    expect(init?.method).toBe("POST");
    expect((init?.headers as Record<string, string>)["X-Analyst-Token"]).toBe(TOKEN);
    expect(JSON.parse(String(init?.body))).toEqual(body);
  });

  it("surfaces the server's reason for a refusal", async () => {
    mockFetch({ "/action": () => jsonResponse({ detail: "ring already decided" }, 409) });
    const err = await createSource(API_CFG)
      .act(firstId, { action: "confirm", analyst: "a", note: "", idempotency_key: "k".repeat(20) }, TOKEN)
      .catch((e) => e);
    expect(err).toBeInstanceOf(HttpError);
    expect(err.status).toBe(409);
    expect(err.message).toBe("ring already decided");
  });

  it("refuses to act without an API", async () => {
    await expect(createSource({ apiBase: "", timeoutMs: 500 }).act(firstId, { action: "hold", analyst: "a", note: "", idempotency_key: "k".repeat(20) }, TOKEN)).rejects.toThrow(/no API/);
  });

  it("reports no feedback state offline", async () => {
    expect(await createSource({ apiBase: "", timeoutMs: 500 }).feedback()).toBeNull();
  });
});

function caseRoute(status: string, n_actions = 0) {
  return { [`/api/v1/cases/${firstId}`]: () => jsonResponse({ ...cases.cases[firstId], status, n_actions }) };
}

describe("Decision panel", () => {
  it("explains that snapshots cannot record decisions", async () => {
    mockFetch(snapshotRoutes());
    renderWith(<CaseView ringId={firstId} />);
    expect(await screen.findByText(/nothing to record against/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /confirm ring/i })).toBeNull();
  });

  it("keeps the buttons off until a name and a long-enough token are entered", async () => {
    mockFetch(caseRoute("pending"));
    renderWith(<CaseView ringId={firstId} />, createSource(API_CFG));
    const confirm = await screen.findByRole("button", { name: /confirm ring/i });
    expect(confirm).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/your name/i), "asha");
    await userEvent.type(screen.getByLabelText(/analyst token/i), "short");
    expect(confirm).toBeDisabled();
    await userEvent.clear(screen.getByLabelText(/analyst token/i));
    await userEvent.type(screen.getByLabelText(/analyst token/i), TOKEN);
    expect(confirm).toBeEnabled();
  });

  it("records a decision, shows the audit entry number and reloads the case", async () => {
    let status = "pending";
    const f = mockFetch({
      "/action": () => {
        status = "confirmed";
        return jsonResponse({ ring_id: firstId, status, replayed: false, entry: entry(7, "confirm") }, 201);
      },
      [`/api/v1/cases/${firstId}`]: () => jsonResponse({ ...cases.cases[firstId], status, n_actions: status === "pending" ? 0 : 1 }),
    });
    renderWith(<CaseView ringId={firstId} />, createSource(API_CFG));
    await screen.findByRole("button", { name: /confirm ring/i });
    await fillForm();
    await userEvent.type(screen.getByLabelText(/note/i), "device shared");
    await userEvent.click(screen.getByRole("button", { name: /confirm ring/i }));
    expect(await screen.findByText(/audit entry #7/i)).toBeInTheDocument();
    const post = f.mock.calls.find(([, init]) => init?.method === "POST")!;
    const sent = JSON.parse(String(post[1]?.body));
    expect(sent).toMatchObject({ action: "confirm", analyst: "asha", note: "device shared" });
    expect(sent.idempotency_key).toMatch(/^[A-Za-z0-9_-]{16,64}$/);
    // the case reloads and is now closed
    expect(await screen.findByText(/already/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /dismiss/i })).toBeNull();
  });

  it("does not remember the token unless asked, and remembers it for this tab when asked", async () => {
    mockFetch({
      "/action": () => jsonResponse({ ring_id: firstId, status: "held", replayed: false, entry: entry(1, "hold") }, 201),
      ...caseRoute("pending"),
    });
    renderWith(<CaseView ringId={firstId} />, createSource(API_CFG));
    await screen.findByRole("button", { name: /^hold$/i });
    await fillForm();
    await userEvent.click(screen.getByRole("button", { name: /^hold$/i }));
    await screen.findByText(/audit entry #1/i);
    expect(window.sessionStorage.getItem("rs_analyst_token")).toBeNull();
    await userEvent.click(screen.getByLabelText(/remember the token/i));
    await userEvent.click(screen.getByRole("button", { name: /^hold$/i }));
    await waitFor(() => expect(window.sessionStorage.getItem("rs_analyst_token")).toBe(TOKEN));
  });

  it("offers only confirm and dismiss for a held ring", async () => {
    mockFetch(caseRoute("held", 1));
    renderWith(<CaseView ringId={firstId} />, createSource(API_CFG));
    await screen.findByRole("button", { name: /confirm ring/i });
    expect(screen.getByRole("button", { name: /dismiss/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^hold$/i })).toBeNull();
  });

  it.each(["confirmed", "dismissed"])("shows a %s ring as closed with no buttons", async (st) => {
    mockFetch(caseRoute(st, 1));
    renderWith(<CaseView ringId={firstId} />, createSource(API_CFG));
    expect(await screen.findByText(/a decided case is closed/i)).toBeInTheDocument();
    expect(within(screen.getByTestId("action-panel")).queryAllByRole("button")).toHaveLength(0);
  });

  it.each([
    [401, /token was not accepted/i],
    [503, /RS_ANALYST_TOKEN/],
    [429, /too many requests/i],
    [409, /refused this decision: ring already decided/i],
  ])("explains a %s answer in plain words", async (code, text) => {
    mockFetch({ "/action": () => jsonResponse({ detail: "ring already decided" }, code as number), ...caseRoute("pending") });
    renderWith(<CaseView ringId={firstId} />, createSource(API_CFG));
    await screen.findByRole("button", { name: /confirm ring/i });
    await fillForm();
    await userEvent.click(screen.getByRole("button", { name: /confirm ring/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
  });

  it("reuses the idempotency key when the same decision is retried after a network failure", async () => {
    let calls = 0;
    const f = mockFetch({
      "/action": () => {
        calls += 1;
        if (calls === 1) throw new TypeError("network down");
        return jsonResponse({ ring_id: firstId, status: "dismissed", replayed: calls > 2, entry: entry(2, "dismiss") }, 201);
      },
      ...caseRoute("pending"),
    });
    renderWith(<CaseView ringId={firstId} />, createSource(API_CFG));
    await screen.findByRole("button", { name: /dismiss/i });
    await fillForm();
    await userEvent.click(screen.getByRole("button", { name: /dismiss/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/safe to retry/i);
    await userEvent.click(screen.getByRole("button", { name: /dismiss/i }));
    await screen.findByText(/audit entry #2/i);
    const keys = f.mock.calls.filter(([, i]) => i?.method === "POST").map(([, i]) => JSON.parse(String(i?.body)).idempotency_key);
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });

  it("warns that a snapshot case may be stale when the API is configured but down", async () => {
    mockFetch(snapshotRoutes());
    renderWith(<CaseView ringId={firstId} />, createSource(API_CFG));
    expect(await screen.findByText(/read from a saved snapshot/i)).toBeInTheDocument();
  });
});

describe("Review queue with analyst feedback", () => {
  const feedback = {
    base_threshold: 0.3, effective_threshold: 0.36, offset_logit: 0.3, max_offset_logit: 1.5, step_logit: 0.1, confirm_weight: 1,
    at_bound: false, n_confirmed: 1, n_dismissed: 3, n_held: 0, n_pending: 10, n_active: 9, n_deprioritised: 1, n_in_bundle: 14,
    rule: "Each net dismissal raises the threshold by 0.1 log-odds.", validated: false, note: "A heuristic.",
  };
  function liveItems() {
    return queue.items.map((i: { score: number }, n: number) => ({
      ...i,
      status: n === 0 ? "confirmed" : "pending",
      live: { adjusted_score: i.score, adjusted_expected_value_inr: 1000 - n, above_threshold: n < 9, live_rank: n === 0 || n >= 9 ? null : n },
    }));
  }

  it("requests the live order and shows the feedback card and live columns", async () => {
    const f = mockFetch({ "/api/v1/queue": () => jsonResponse({ ...queue, items: liveItems(), order: "live", feedback }) });
    renderWith(<QueueView />, createSource(API_CFG));
    await screen.findByRole("table");
    expect(String(f.mock.calls[0]![0])).toContain("order=live");
    expect(screen.getByTestId("feedback-card")).toHaveTextContent(/threshold 0.360 \(base 0.300\)/i);
    expect(screen.getByRole("columnheader", { name: /live order/i })).toBeInTheDocument();
    expect(screen.getAllByText("decided")).toHaveLength(1);
    expect(screen.getAllByText("below threshold").length).toBeGreaterThan(0);
    expect(screen.getByText(/a heuristic/i)).toBeInTheDocument();
  });

  it("switches to the exported order and asks the API again", async () => {
    const f = mockFetch({ "/api/v1/queue": () => jsonResponse({ ...queue, items: liveItems(), order: "live", feedback }) });
    renderWith(<QueueView />, createSource(API_CFG));
    await screen.findByRole("table");
    await userEvent.selectOptions(screen.getByLabelText(/^order$/i), "export");
    await waitFor(() => expect(f.mock.calls.some(([u]) => String(u).includes("order=export"))).toBe(true));
  });

  it("says when the shift has reached its limit", async () => {
    mockFetch({ "/api/v1/queue": () => jsonResponse({ ...queue, items: liveItems(), order: "live", feedback: { ...feedback, offset_logit: 1.5, at_bound: true } }) });
    renderWith(<QueueView />, createSource(API_CFG));
    expect(await screen.findByText(/at the limit/i)).toBeInTheDocument();
  });

  it("shows no feedback card and no order switch from a snapshot", async () => {
    mockFetch(snapshotRoutes());
    renderWith(<QueueView />);
    await screen.findByRole("table");
    expect(screen.queryByTestId("feedback-card")).toBeNull();
    expect(screen.queryByLabelText(/^order$/i)).toBeNull();
    expect(screen.queryByRole("columnheader", { name: /live order/i })).toBeNull();
  });
});

describe("Drift page", () => {
  it("raises an alert for the shifted windows of the demo bundle and marks them in text", async () => {
    mockFetch(snapshotRoutes());
    renderWith(<DriftView />);
    const status = await screen.findByTestId("drift-status");
    expect(status).toHaveTextContent(/drift alert/i);
    const levels = screen.getAllByTestId("drift-bar").map((b) => b.getAttribute("data-level"));
    expect(levels.slice(0, 5)).toEqual(["ok", "ok", "ok", "ok", "ok"]);
    expect(levels.slice(-2)).toEqual(["alert", "alert"]);
    expect(screen.getAllByText("ALERT")).toHaveLength(2);
    expect(screen.getByRole("img", { name: /2 window\(s\) above the alert level/i })).toBeInTheDocument();
  });

  it("is quiet when no window is above the warn level", async () => {
    const calm = {
      ...drift,
      windows: drift.windows.map((w: object) => ({ ...w, psi: 0.01, level: "ok" })),
      summary: { ...drift.summary, n_alert: 0, n_warn: 0, alert_windows: [], first_alert_index: null, max_psi: 0.01 },
    };
    mockFetch({ "/snapshots/drift.json": () => jsonResponse(calm) });
    renderWith(<DriftView />);
    expect(await screen.findByTestId("drift-status")).toHaveTextContent(/stable/i);
    expect(screen.queryByText("ALERT")).toBeNull();
    expect(screen.queryByText(/drift alert/i)).toBeNull();
  });

  it("separates a warning from an alert", async () => {
    const warn = {
      ...drift,
      windows: drift.windows.map((w: object, i: number) => ({ ...w, psi: i === 3 ? 0.15 : 0.01, level: i === 3 ? "warn" : "ok" })),
      summary: { ...drift.summary, n_alert: 0, n_warn: 1, alert_windows: [], first_alert_index: null },
    };
    mockFetch({ "/snapshots/drift.json": () => jsonResponse(warn) });
    renderWith(<DriftView />);
    expect(await screen.findByTestId("drift-status")).toHaveTextContent(/drifting/i);
  });

  it("says plainly when drift was not computed", async () => {
    mockFetch({ "/snapshots/drift.json": () => jsonResponse({ schema_version: "1", status: "not_built", built_in_stage: "07", psi_alert_level: null, windows: [] }) });
    renderWith(<DriftView />);
    expect(await screen.findByText(/drift was not computed/i)).toBeInTheDocument();
  });

  it("handles a window with too few events", async () => {
    const thin = { ...drift, windows: drift.windows.map((w: object, i: number) => (i === 0 ? { ...w, psi: null, level: "insufficient" } : w)) };
    mockFetch({ "/snapshots/drift.json": () => jsonResponse(thin) });
    renderWith(<DriftView />);
    await screen.findByTestId("drift-chart");
    expect(screen.getByText("too few")).toBeInTheDocument();
    expect(screen.getAllByText("n/a").length).toBeGreaterThan(0);
  });
});

describe("Replay page", () => {
  it("starts at the end, then steps back and forward through detections", async () => {
    mockFetch(snapshotRoutes());
    renderWith(<ReplayView />);
    const status = await screen.findByTestId("replay-status");
    expect(status).toHaveTextContent(`${replay.events.length} of ${replay.events.length} flagged rings detectable`);
    const slider = screen.getByLabelText(/replay time/i);
    fireEvent.change(slider, { target: { value: "0" } });
    expect(screen.getByTestId("replay-status")).toHaveTextContent(/0 of 10 flagged rings|\d+ of 10 flagged rings/);
    expect(screen.getByRole("button", { name: /step back/i })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /step forward/i }));
    expect(screen.getByRole("button", { name: /step back/i })).toBeEnabled();
  });

  it("lists detected rings with latency against the truth where one exists", async () => {
    mockFetch(snapshotRoutes());
    renderWith(<ReplayView />);
    await screen.findByTestId("replay-status");
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows.length).toBeGreaterThanOrEqual(replay.events.length);
    const withTruth = replay.events.filter((e) => e.latency_minutes != null).length;
    expect(withTruth).toBeGreaterThan(0);
    expect(screen.getAllByText("n/a").length).toBeGreaterThan(0);
  });

  it("shows nothing detected at the start and a message", async () => {
    mockFetch({ "/snapshots/replay.json": () => jsonResponse({ ...replay, events: replay.events.map((e) => ({ ...e, detected_ts: "2099-01-01T00:00:00" })) }) });
    renderWith(<ReplayView />);
    await screen.findByTestId("replay-status");
    expect(screen.getByText(/none yet/i)).toBeInTheDocument();
  });

  it("renders identically twice (deterministic)", async () => {
    mockFetch(snapshotRoutes());
    const a = renderWith(<ReplayView />);
    await screen.findByTestId("replay-status");
    const first = a.container.innerHTML;
    a.unmount();
    const b = renderWith(<ReplayView />);
    await screen.findByTestId("replay-status");
    expect(b.container.innerHTML).toBe(first);
  });

  it("says plainly when replay was not built", async () => {
    mockFetch({ "/snapshots/replay.json": () => jsonResponse({ schema_version: "1", status: "not_built", built_in_stage: "07", events: [] }) });
    renderWith(<ReplayView />);
    expect(await screen.findByText(/replay was not built/i)).toBeInTheDocument();
  });

  it("marks a partial detection", async () => {
    const events = replay.events.map((e, i) => (i === 0 ? { ...e, partial: true } : e));
    mockFetch({ "/snapshots/replay.json": () => jsonResponse({ ...replay, events }) });
    renderWith(<ReplayView />);
    await screen.findByTestId("replay-status");
    expect(screen.getByText("partial")).toBeInTheDocument();
  });
});

describe("Scripted analyst scenario (plan M7 test)", () => {
  it("opens the queue, opens a case, acts, sees the audit entry, and replays", async () => {
    const log: ReturnType<typeof entry>[] = [];
    let status = "pending";
    mockFetch({
      "/api/v1/queue": () => jsonResponse({ ...queue, items: queue.items.map((i: object, n: number) => ({ ...i, status: n === 0 ? status : "pending" })), order: "live" }),
      "/action": () => {
        status = "confirmed";
        log.push(entry(1, "confirm"));
        return jsonResponse({ ring_id: firstId, status, replayed: false, entry: log[0] }, 201);
      },
      [`/api/v1/cases/${firstId}`]: () => jsonResponse({ ...cases.cases[firstId], status, n_actions: log.length }),
      "/audit/verify": () => jsonResponse({ ok: true, entries: log.length, head_hash: log.length ? "a".repeat(64) : null, first_bad_seq: null, reason: null }),
      "/audit?": () => jsonResponse({ total: log.length, entries: log }),
      "/api/v1/replay": () => jsonResponse(replay),
    });
    const source = createSource(API_CFG);

    const queueView = renderWith(<QueueView />, source);
    expect(await screen.findByRole("link", { name: firstId })).toBeInTheDocument(); // 1. open the queue
    queueView.unmount();

    const caseView = renderWith(<CaseView ringId={firstId} />, source); // 2. open the case
    await screen.findByRole("button", { name: /confirm ring/i });
    await fillForm();
    await userEvent.click(screen.getByRole("button", { name: /confirm ring/i })); // 3. act
    expect(await screen.findByText(/audit entry #1/i)).toBeInTheDocument();
    caseView.unmount();

    const audit = renderWith(<AuditView />, source); // 4. the audit entry is visible
    expect(await screen.findByText("chain intact")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/analyst token/i), TOKEN);
    await userEvent.click(screen.getByRole("button", { name: /show entries/i }));
    expect(await screen.findByText(/confirm/)).toBeInTheDocument();
    audit.unmount();

    renderWith(<ReplayView />, source); // 5. replay
    expect(await screen.findByTestId("replay-status")).toBeInTheDocument();
  });
});
