"""A deterministic stand-in for a language model, for demos and integration tests.

`HeuristicProvider` follows the real protocol (one tool call, then a final answer, built only from
what the tools returned) so the whole pipeline can run without a key. Its output is plain
templated text. It is NOT a model, and blocks it writes name `fake` as their provider so they
cannot be mistaken for real model output.
"""

from __future__ import annotations

from ringsentinel.ai.prompts import read_tagged_json
from ringsentinel.ai.provider import Message, ProviderError

_BENIGN_BY_SHAPE = {
    "fan_out": "marketplace_or_settlement",
    "fan_in": "marketplace_or_settlement",
    "chain": "payroll_or_recurring",
    "cycle": "treasury_or_internal_sweep",
    "gather_scatter": "marketplace_or_settlement",
    "dense_cluster": "shared_household_or_family",
}


def _band(score: float) -> str:
    return "high" if score >= 0.7 else "medium" if score >= 0.3 else "low"


class HeuristicProvider:
    name = "fake"
    model = "heuristic-v1"

    def generate(self, system: str, messages: list[Message], **kwargs) -> str:
        import json

        if system.startswith("TASK: investigator"):
            return json.dumps(self._investigator(messages))
        if system.startswith("TASK: devils_advocate"):
            return json.dumps(self._advocate(messages))
        if system.startswith("TASK: query"):
            return json.dumps(self._query(messages))
        raise ProviderError("the fake provider does not know this task")

    # ------------------------------------------------------------------ tasks
    def _investigator(self, messages: list[Message]) -> dict:
        context = read_tagged_json(messages[0].content, "CASE_CONTEXT") or {}
        stats = context.get("stats", {})
        weights = next(
            (read_tagged_json(m.content, "TOOL_RESULT", "edge_weights") for m in messages
             if m.role == "user" and m.content.startswith("TOOL_RESULT edge_weights")),
            None,
        )  # fmt: skip
        if weights is None and stats.get("n_edges", 0) > 0:
            return {"type": "tool_call", "tool": "edge_weights", "args": {"top_n": 3}}
        shape = stats.get("structure", "unclear")
        total = f"{stats['ring_total_inr']:,.2f}"
        findings = [
            {
                "text": f"{stats['n_members']} accounts made {stats['n_transfers']} transfers "
                        f"worth INR {total}.",
                "counts": [
                    {"metric": "n_members", "value": stats["n_members"]},
                    {"metric": "n_transfers", "value": stats["n_transfers"]},
                ],
                "amounts": [{"metric": "ring_total_inr", "value_inr": stats["ring_total_inr"]}],
            }
        ]  # fmt: skip
        if weights and weights.get("edges"):
            top = weights["edges"][0]
            findings.append(
                {
                    "text": f"The heaviest edge is {top['from']} to {top['to']}: INR "
                            f"{top['total_inr']:,.2f} over {top['n_transfers']} transfers.",
                    "nodes": [top["from"], top["to"]],
                    "counts": [{"metric": "edge_n_transfers", "account": top["from"],
                                "counterparty": top["to"], "value": top["n_transfers"]}],
                    "amounts": [{"metric": "edge_total_inr", "account": top["from"],
                                 "counterparty": top["to"], "value_inr": top["total_inr"]}],
                }
            )  # fmt: skip
        return {
            "type": "case_file", "pattern": shape if shape != "star" else "other",
            "suspicion": _band(float(context.get("detector_score_uncalibrated", 0.0))),
            "summary": f"Templated demo text: {stats['n_members']} accounts, "
                       f"{stats['n_transfers']} transfers, INR {total}.",
            "findings": findings, "key_accounts": [],
            "limits": "Written by the fake demo provider, not by a language model.",
            "suggested_checks": ["Check whether the accounts share an owner."],
        }  # fmt: skip

    def _advocate(self, messages: list[Message]) -> dict:
        context = read_tagged_json(messages[0].content, "CASE_CONTEXT") or {}
        first_pass = read_tagged_json(messages[0].content, "FIRST_PASS_CASE_FILE") or {}
        stats = context.get("stats", {})
        label = _BENIGN_BY_SHAPE.get(stats.get("structure", ""), "small_business_activity")
        plausibility = {"low": "high", "medium": "medium", "high": "low"}[
            first_pass.get("suspicion", "medium")
        ]
        return {
            "type": "benign_case", "plausibility": plausibility,
            "summary": "Templated demo text: ordinary activity could look like this.",
            "hypotheses": [
                {
                    "label": label,
                    "argument": f"{stats['n_members']} accounts and {stats['n_transfers']} "
                                "transfers could be ordinary business flows.",
                    "counts": [
                        {"metric": "n_members", "value": stats["n_members"]},
                        {"metric": "n_transfers", "value": stats["n_transfers"]},
                    ],
                    "strength": plausibility,
                    "how_to_check": "Compare with onboarding records.",
                }
            ],
            "weakest_point": "Only transfers are visible, not the reason for them.",
        }  # fmt: skip

    def _query(self, messages: list[Message]) -> dict:
        text = messages[-1].content.lower()
        filters: list[dict] = []
        if "unverified" in text:
            filters.append({"field": "verifier_status", "op": "eq", "value": "unverified"})
        elif "verified" in text:
            filters.append({"field": "verifier_status", "op": "eq", "value": "verified"})
        if "contested" in text:
            filters.append({"field": "contested", "op": "eq", "value": True})
        if "oversized" in text:
            filters.append({"field": "oversized", "op": "eq", "value": True})
        if "template" in text:
            filters.append({"field": "source", "op": "eq", "value": "template"})
        return {"filters": filters, "sort_by": "rank", "direction": "asc", "limit": 20}
