import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "@/components/AppShell";
import { AuditView } from "@/components/AuditView";
import { CaseView } from "@/components/CaseView";
import { MetricsView } from "@/components/MetricsView";
import { QueueView } from "@/components/QueueView";
import { createSource } from "@/lib/source";
import { API_CFG, OFFLINE_CFG, demoDoc, jsonResponse, mockFetch, renderWith, snapshotRoutes } from "./helpers";

vi.mock("next/navigation", () => ({ usePathname: () => "/", useSearchParams: () => new URLSearchParams() }));
afterEach(() => vi.unstubAllGlobals());

const queue = demoDoc("queue.json");
const firstId: string = queue.items[0].ring_id;
const bigId: string = queue.items.find((i: { oversized: boolean }) => i.oversized).ring_id;

describe("Review queue", () => {
  it("shows a loading state, then the ranked rings", async () => {
    mockFetch(snapshotRoutes());
    renderWith(<QueueView />);
    expect(screen.getByRole("status")).toHaveTextContent(/loading/i);
    expect(await screen.findByRole("table")).toBeInTheDocument();
    const rows = screen.getAllByRole("row");
    expect(rows.length).toBe(1 + 14); // header + all demo rings fit on one page of 25
    expect(within(rows[1]!).getByRole("link")).toHaveTextContent(firstId);
    expect(screen.getAllByText(/not a calibrated probability/i).length).toBeGreaterThan(0);
  });

  it("links each ring to its case page by query string", async () => {
    mockFetch(snapshotRoutes());
    renderWith(<QueueView />);
    const link = await screen.findByRole("link", { name: firstId });
    expect(link.getAttribute("href")).toMatch(new RegExp(`^/case/?\\?id=${firstId}$`)); // trailing slash is added by next.config trailingSlash
  });

  it("filters by ring id and shows an empty-filter state", async () => {
    mockFetch(snapshotRoutes());
    renderWith(<QueueView />);
    await screen.findByRole("table");
    await userEvent.type(screen.getByLabelText(/search ring id/i), firstId.slice(0, 8));
    expect(screen.getAllByRole("row")).toHaveLength(2);
    await userEvent.clear(screen.getByLabelText(/search ring id/i));
    await userEvent.type(screen.getByLabelText(/search ring id/i), "zzzz");
    expect(screen.getByText(/no rings match/i)).toBeInTheDocument();
  });

  it("explains that decisions are unknown offline and disables the status filter", async () => {
    mockFetch(snapshotRoutes());
    renderWith(<QueueView />);
    await screen.findByRole("table");
    expect(screen.getByLabelText(/^status$/i)).toBeDisabled();
    expect(screen.getAllByText("not tracked").length).toBeGreaterThan(0);
    expect(screen.getByTestId("origin-note")).toHaveTextContent(/saved snapshot/i);
  });

  it("uses live statuses and the status filter when the API answers", async () => {
    const items = queue.items.map((i: object, n: number) => ({ ...i, status: n === 0 ? "confirmed" : "pending" }));
    mockFetch({ "http://api.test/api/v1/queue": () => jsonResponse({ ...queue, items, total: items.length }) });
    renderWith(<QueueView />, createSource(API_CFG));
    await screen.findByRole("table");
    expect(screen.queryByTestId("origin-note")).toBeNull();
    await userEvent.selectOptions(screen.getByLabelText(/^status$/i), "confirmed");
    expect(screen.getAllByRole("row")).toHaveLength(2);
  });

  it("shows an empty state when nothing was flagged", async () => {
    mockFetch({ "/snapshots/queue.json": () => jsonResponse({ ...queue, items: [], note: "validation net value was negative" }) });
    renderWith(<QueueView />);
    expect(await screen.findByText(/no rings to review/i)).toBeInTheDocument();
    expect(screen.getAllByText(/validation net value was negative/).length).toBeGreaterThan(0);
  });

  it("pages through long queues", async () => {
    const many = Array.from({ length: 60 }, (_, i) => ({ ...queue.items[0], ring_id: `R-${String(i).padStart(12, "0")}`, rank: i + 1 }));
    mockFetch({ "/snapshots/queue.json": () => jsonResponse({ ...queue, items: many }) });
    renderWith(<QueueView />);
    await screen.findByRole("table");
    expect(screen.getAllByRole("row")).toHaveLength(26);
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(screen.getByText(/page 2 of 3/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /previous/i })).toBeEnabled();
  });

  it("shows an error with a retry when every source fails", async () => {
    mockFetch({});
    renderWith(<QueueView />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not load data/i);
    mockFetch(snapshotRoutes());
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByRole("table")).toBeInTheDocument();
  });
});

describe("Case view", () => {
  it("renders the graph, signals and the explanation card", async () => {
    mockFetch(snapshotRoutes());
    renderWith(<CaseView ringId={firstId} />);
    expect(await screen.findByTestId("graph-svg")).toBeInTheDocument();
    expect(screen.getAllByTestId("graph-node").length).toBeGreaterThan(3);
    expect(screen.getByTestId("ai-source")).toHaveTextContent(/rule-based summary, no language model/i);
    expect(screen.getByText(/why it was flagged/i)).toBeInTheDocument();
  });

  it("caps the graph at 500 accounts for the oversized ring and says so", async () => {
    mockFetch(snapshotRoutes());
    renderWith(<CaseView ringId={bigId} />);
    await screen.findByTestId("graph-svg");
    expect(screen.getAllByTestId("graph-node")).toHaveLength(500);
    expect(screen.getByTestId("graph-summary")).toHaveTextContent(/showing 500 of \d+ accounts/i);
    expect(screen.getByTestId("graph-summary")).toHaveTextContent(/capped at 500/i);
  });

  it("selects an account with the keyboard", async () => {
    mockFetch(snapshotRoutes());
    renderWith(<CaseView ringId={firstId} />);
    const node = (await screen.findAllByTestId("graph-node"))[0]!;
    fireEvent.keyDown(node, { key: "Enter" });
    expect(await screen.findByText("Sent")).toBeInTheDocument();
  });

  it("works with the backend unreachable (API configured, snapshot answers)", async () => {
    mockFetch(snapshotRoutes());
    renderWith(<CaseView ringId={firstId} />, createSource(API_CFG));
    expect(await screen.findByTestId("graph-svg")).toBeInTheDocument();
    expect(screen.getByTestId("origin-note")).toHaveTextContent(/backend unavailable/i);
  });

  it("asks for a ring when none is selected, and handles an unknown ring", async () => {
    mockFetch(snapshotRoutes());
    const { unmount } = renderWith(<CaseView ringId={null} />);
    expect(screen.getByText(/no ring selected/i)).toBeInTheDocument();
    unmount();
    renderWith(<CaseView ringId="R-000000000000" />);
    expect(await screen.findByText(/ring not found/i)).toBeInTheDocument();
  });

  it("shows a clear state when the bundle has no edges", async () => {
    const cases = demoDoc("cases.json");
    cases.cases[firstId] = { ...cases.cases[firstId], edges: [], edges_available: false };
    mockFetch({ "/snapshots/cases.json": () => jsonResponse(cases) });
    renderWith(<CaseView ringId={firstId} />);
    expect(await screen.findByText(/no transfer graph in this bundle/i)).toBeInTheDocument();
  });
});

describe("Metrics", () => {
  it("renders the results table, curves, ablations, robustness and latency", async () => {
    mockFetch(snapshotRoutes());
    renderWith(<MetricsView />);
    expect(await screen.findByTestId("results-table")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /precision and recall/i })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /ring-level precision against recall/i })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /test net value against/i })).toBeInTheDocument();
    expect(screen.getByText("Graph, hub control on")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /test pr-auc as more transfers/i })).toBeInTheDocument();
    expect(screen.queryByTestId("not-in-bundle")).toBeNull();
  });

  it("changes the cost curve when the review cost changes", async () => {
    mockFetch(snapshotRoutes());
    renderWith(<MetricsView />);
    await screen.findByTestId("results-table");
    const before = screen.getByRole("img", { name: /test net value against/i }).innerHTML;
    await userEvent.selectOptions(screen.getByLabelText(/review cost/i), "500");
    expect(screen.getByRole("img", { name: /test net value against/i }).innerHTML).not.toBe(before);
  });

  it("says plainly when a section is missing or not recognised, instead of drawing nothing", async () => {
    const m = demoDoc("metrics.json");
    mockFetch({ "/snapshots/metrics.json": () => jsonResponse({ ...m, cost_sweep: [], ablations: {}, robustness: {}, latency: {}, results_table_md: null }) });
    renderWith(<MetricsView />);
    await screen.findByRole("heading", { name: /detector comparison/i });
    expect(screen.getAllByTestId("not-in-bundle").length).toBeGreaterThanOrEqual(4);
    expect(screen.getByTestId("summary-table")).toBeInTheDocument(); // falls back to the documented summary fields
  });
});

describe("Audit log", () => {
  it("explains that snapshot-only mode has no audit log", async () => {
    mockFetch({});
    renderWith(<AuditView />);
    expect(await screen.findByText(/the audit log needs the backend/i)).toBeInTheDocument();
  });

  it("shows an offline state with retry when the API is configured but down", async () => {
    mockFetch({});
    renderWith(<AuditView />, createSource(API_CFG));
    expect(await screen.findByText(/backend unreachable/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });

  const entry = { seq: 1, ts: "2026-11-13T05:00:00.000000Z", ring_id: firstId, action: "hold", analyst: "deepa", note: "check device", idempotency_key: "k".repeat(16), prev_hash: "0".repeat(64), hash: "a".repeat(64) };

  it("shows chain status, then the list after a token is entered", async () => {
    const f = mockFetch({
      "/audit/verify": () => jsonResponse({ ok: true, entries: 1, head_hash: "a".repeat(64), first_bad_seq: null, reason: null }),
      "/audit?": (_u, init) =>
        (init?.headers as Record<string, string>)["X-Analyst-Token"] === "good-token-123456789" ? jsonResponse({ total: 1, entries: [entry] }) : jsonResponse({ detail: "bad" }, 401),
    });
    renderWith(<AuditView />, createSource(API_CFG));
    expect(await screen.findByText("chain intact")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/analyst token/i), "wrong-token-1234567");
    await userEvent.click(screen.getByRole("button", { name: /show entries/i }));
    expect(await screen.findByText(/token was not accepted/i)).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText(/analyst token/i));
    await userEvent.type(screen.getByLabelText(/analyst token/i), "good-token-123456789");
    await userEvent.click(screen.getByRole("button", { name: /show entries/i }));
    expect(await screen.findByText("check device")).toBeInTheDocument();
    expect(f).toHaveBeenCalled();
    expect(window.sessionStorage.getItem("rs_analyst_token")).toBeNull(); // not remembered unless asked
  });

  it("reports a broken chain loudly", async () => {
    mockFetch({ "/audit/verify": () => jsonResponse({ ok: false, entries: 5, head_hash: null, first_bad_seq: 3, reason: "hash mismatch" }) });
    renderWith(<AuditView />, createSource(API_CFG));
    expect(await screen.findByText("chain broken")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/#3/);
  });

  it("explains a 503 (no token configured on the server)", async () => {
    mockFetch({
      "/audit/verify": () => jsonResponse({ ok: true, entries: 0, head_hash: null, first_bad_seq: null, reason: null }),
      "/audit?": () => jsonResponse({ detail: "not configured" }, 503),
    });
    renderWith(<AuditView />, createSource(API_CFG));
    await screen.findByText("chain intact");
    await userEvent.type(screen.getByLabelText(/analyst token/i), "any-token-1234567890");
    await userEvent.click(screen.getByRole("button", { name: /show entries/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/RS_ANALYST_TOKEN/));
  });
});

describe("App shell with the backend unreachable (plan test)", () => {
  it("renders the whole queue page from the snapshot and says the backend is down", async () => {
    mockFetch(snapshotRoutes());
    const source = createSource(API_CFG);
    renderWith(
      <AppShell source={source}>
        <QueueView />
      </AppShell>,
      source,
    );
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(await screen.findByText(/backend unreachable: using saved snapshot/i)).toBeInTheDocument();
    expect(screen.getByText(/demo data\./i)).toBeInTheDocument(); // the demo banner
    expect(screen.getByRole("link", { name: /review queue/i })).toHaveAttribute("aria-current", "page");
  });

  it("shows the live chip when the API answers", async () => {
    mockFetch({
      ...snapshotRoutes(),
      "/snapshots/meta.json": () => jsonResponse({ ...demoDoc("meta.json"), dataset_variant: "HI-Small", evaluation_frozen: true }),
      "/api/v1/health": () => jsonResponse({ status: "ok", bundle_id: "b".repeat(64), schema_version: "1", evaluation_frozen: true, git_commit: "x", n_rings: 3, audit_entries: 0, actions_enabled: true }),
    });
    const source = createSource(API_CFG);
    renderWith(<AppShell source={source}><p>child</p></AppShell>, source);
    expect(await screen.findByText("Live API")).toBeInTheDocument();
  });

  it("warns when the saved snapshot is not the bundle the live API serves", async () => {
    mockFetch({
      ...snapshotRoutes(),
      "/api/v1/health": () => jsonResponse({ status: "ok", bundle_id: "c".repeat(64), schema_version: "1", evaluation_frozen: false, git_commit: "x", n_rings: 3, audit_entries: 0, actions_enabled: true }),
    });
    const source = createSource(API_CFG);
    renderWith(<AppShell source={source}><p>child</p></AppShell>, source);
    expect(await screen.findByText(/snapshot out of date/i)).toBeInTheDocument();
  });

  it("warns when the numbers are not frozen on a non-demo bundle", async () => {
    const meta = { ...demoDoc("meta.json"), dataset_variant: "HI-Small", evaluation_frozen: false };
    mockFetch({ "/snapshots/meta.json": () => jsonResponse(meta) });
    renderWith(<AppShell source={createSource(OFFLINE_CFG)}><p>child</p></AppShell>);
    expect(await screen.findByText(/numbers not frozen/i)).toBeInTheDocument();
    expect(screen.queryByText(/demo data\./i)).toBeNull();
  });
});
