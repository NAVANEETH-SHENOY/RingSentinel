"""Offline fallback: a case file written by plain code from the ring's own facts.

Used when no provider is configured, the provider is down and nothing is cached, or the model
produced no valid answer. It states only recomputable facts, so it passes the verifier by
construction (the pipeline still runs the verifier on it). Its `suspicion` is a band of the
detector score, not an independent reading, and the case file says so.
"""

from __future__ import annotations

from ringsentinel.ai.facts import CaseFacts
from ringsentinel.ai.schemas import AmountClaim, CaseFile, CountClaim, Finding, KeyAccount

_SHAPE_TEXT = {
    "fan_out": "one account sends to many",
    "fan_in": "many accounts send to one",
    "chain": "a chain of hand-offs",
    "cycle": "money returning along a cycle",
    "gather_scatter": "a hub that collects and redistributes",
    "dense_cluster": "a dense cluster of mutual transfers",
    "other": "no single textbook shape",
    "unclear": "no edge data to describe a shape",
}
_CHECKS = [
    "Check whether the listed accounts share an owner, address or onboarding documents.",
    "Review the largest transfers first.",
]


def score_band(score: float) -> str:
    return "high" if score >= 0.7 else "medium" if score >= 0.3 else "low"


def _role(facts: CaseFacts, real: str) -> str:
    if not facts.in_edges(real):
        return "source"
    if not facts.out_edges(real):
        return "sink"
    return "relay"


def template_case_file(facts: CaseFacts) -> CaseFile:
    pattern = facts.structural_pattern()
    total = f"{facts.ring_total_inr:,.2f}"
    summary = (
        f"Ring of {facts.n_members} accounts and {facts.n_transfers} transfers moving INR "
        f"{total}. The retained transfers show {_SHAPE_TEXT[pattern]}."
    )
    findings = [
        Finding(
            text=(
                f"{facts.n_members} accounts made {facts.n_transfers} transfers worth INR {total}."
            ),
            counts=[
                CountClaim(metric="n_members", value=facts.n_members),
                CountClaim(metric="n_transfers", value=facts.n_transfers),
            ],
            amounts=[AmountClaim(metric="ring_total_inr", value_inr=facts.ring_total_inr)],
        )
    ]
    key_accounts: list[KeyAccount] = []
    rows = facts.top_accounts(limit=2)
    if facts.edges and rows:
        top = rows[0]
        scope = "In the retained transfers, " if facts.coverage != "full" else ""
        findings.append(
            Finding(
                text=(
                    f"{scope}{top['account']} is the busiest account: it sent INR "
                    f"{top['out_inr']:,.2f} "
                    f"to {top['out_degree']} accounts and received INR {top['in_inr']:,.2f} "
                    f"from {top['in_degree']}."
                ),
                nodes=[top["account"]],
                counts=[
                    CountClaim(
                        metric="out_degree", account=top["account"], value=top["out_degree"]
                    ),
                    CountClaim(
                        metric="in_degree", account=top["account"], value=top["in_degree"]
                    ),
                ],
                amounts=[
                    AmountClaim(
                        metric="account_out_inr", account=top["account"], value_inr=top["out_inr"]
                    ),
                    AmountClaim(
                        metric="account_in_inr", account=top["account"], value_inr=top["in_inr"]
                    ),
                ],
            )
        )  # fmt: skip
        for row in rows:
            real = facts.resolve(row["account"])
            key_accounts.append(
                KeyAccount(
                    account=row["account"], role=_role(facts, real),  # type: ignore[arg-type]
                    reason="One of the two accounts with the largest transfer volume.",
                )
            )  # fmt: skip
    limits = (
        "Offline template: no language model was used, and the suspicion level is a band of "
        "the detector score, not an independent reading. Only transfers between accounts are "
        "known; owners, devices and intent are not."
    )
    if facts.coverage != "full":
        limits += f" Edge data is {facts.coverage}."
    return CaseFile(
        pattern=pattern,  # type: ignore[arg-type]
        suspicion=score_band(facts.score),  # type: ignore[arg-type]
        summary=summary, findings=findings, key_accounts=key_accounts, limits=limits[:300],
        suggested_checks=list(_CHECKS),
    )  # fmt: skip
