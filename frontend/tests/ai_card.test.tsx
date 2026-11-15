import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CaseView } from "@/components/CaseView";
import { demoDoc, jsonResponse, mockFetch, renderWith, snapshotRoutes } from "./helpers";

vi.mock("next/navigation", () => ({ usePathname: () => "/", useSearchParams: () => new URLSearchParams() }));
afterEach(() => vi.unstubAllGlobals());

const queue = demoDoc("queue.json");
const ringId: string = queue.items[0].ring_id;

const CASE_FILE = {
  type: "case_file",
  pattern: "fan_out",
  suspicion: "high",
  summary: "One source sends to several accounts in a short span.",
  findings: [{ text: "acct source sends to four accounts.", nodes: [], counts: [], amounts: [] }],
  key_accounts: [{ account: "A1", role: "source", reason: "sends most of the volume" }],
  limits: "No device or owner data.",
  suggested_checks: ["Compare opening dates."],
};
const BENIGN = {
  type: "benign_case",
  plausibility: "medium",
  summary: "Could be payroll.",
  hypotheses: [{ label: "payroll_or_recurring", argument: "Equal payments.", nodes: [], counts: [], amounts: [], strength: "medium", how_to_check: "Ask for payroll." }],
  weakest_point: "Irregular timing.",
};

function withAi(ai: Record<string, unknown>) {
  const cases = demoDoc("cases.json");
  cases.cases[ringId] = { ...cases.cases[ringId], ai };
  const routes = snapshotRoutes();
  for (const key of Object.keys(routes)) if (key.endsWith("cases.json")) routes[key] = () => jsonResponse(cases);
  mockFetch(routes);
}

describe("AI case file panel", () => {
  it("shows a verified model-written case file with its limits", async () => {
    withAi({
      status: "ready", built_in_stage: "06", source: "llm", provider: { name: "groq", model: "m" },
      investigator: CASE_FILE, verifier: { status: "verified", issues: [], warnings: [], checked: 3, attempts: 1 },
      benign_explanation: BENIGN, benign_verifier: { status: "verified" }, contested: true, contested_reason: "Both readings fit.",
    });
    renderWith(<CaseView ringId={ringId} />);
    expect(await screen.findByText(CASE_FILE.summary)).toBeInTheDocument();
    expect(screen.getByTestId("ai-verifier")).toHaveTextContent(/facts verified/i);
    expect(screen.getByTestId("ai-source")).toHaveTextContent(/language model/i);
    expect(screen.getByTestId("ai-contested")).toBeInTheDocument();
    expect(screen.getByText(/does not mean the interpretation is right/i)).toBeInTheDocument();
    expect(screen.getByText(/innocent explanation/i)).toBeInTheDocument();
    expect(screen.getByText(/weakest point/i)).toBeInTheDocument();
  });

  it("labels a template summary as rule-based, not model-written", async () => {
    withAi({ status: "ready", built_in_stage: "06", source: "template", investigator: CASE_FILE, verifier: { status: "verified" }, benign_explanation: null });
    renderWith(<CaseView ringId={ringId} />);
    expect(await screen.findByTestId("ai-source")).toHaveTextContent(/rule-based summary, no language model/i);
    expect(screen.getByText(/built by fixed rules/i)).toBeInTheDocument();
  });

  it("does not call the offline stand-in a language model, even when its output is cached", async () => {
    withAi({
      status: "ready", built_in_stage: "06", source: "cache", provider: { name: "fake", model: "heuristic-v1" },
      investigator: CASE_FILE, verifier: { status: "verified" }, benign_explanation: null,
    });
    renderWith(<CaseView ringId={ringId} />);
    const chip = await screen.findByTestId("ai-source");
    expect(chip).toHaveTextContent(/offline stand-in, not a language model/i);
    expect(chip).not.toHaveTextContent(/written by a language model/i);
    expect(screen.getByText(/fixed offline routine used for testing/i)).toBeInTheDocument();
    expect(screen.getByText(/fake \/ heuristic-v1/i)).toBeInTheDocument();
  });

  it("still calls a cached real-provider case model-written", async () => {
    withAi({
      status: "ready", built_in_stage: "06", source: "cache", provider: { name: "groq", model: "m" },
      investigator: CASE_FILE, verifier: { status: "verified" }, benign_explanation: null,
    });
    renderWith(<CaseView ringId={ringId} />);
    expect(await screen.findByTestId("ai-source")).toHaveTextContent(/written by a language model \(cached\)/i);
  });

  it("warns when the facts did not verify", async () => {
    withAi({ status: "ready", built_in_stage: "06", source: "llm", investigator: CASE_FILE, verifier: { status: "unverified", issues: ["amount mismatch"] }, benign_explanation: null });
    renderWith(<CaseView ringId={ringId} />);
    expect(await screen.findByTestId("ai-verifier")).toHaveTextContent(/not verified/i);
    expect(screen.getByText("amount mismatch")).toBeInTheDocument();
  });

  it("renders model text as plain text, never as markup", async () => {
    withAi({
      status: "ready", built_in_stage: "06", source: "llm",
      investigator: { ...CASE_FILE, summary: "<img src=x onerror=alert(1)> hello" },
      verifier: { status: "verified" }, benign_explanation: null,
    });
    const { container } = renderWith(<CaseView ringId={ringId} />);
    expect(await screen.findByText(/hello/)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });
});
