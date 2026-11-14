"""Hand-made cases (tiny, exact numbers) for the Stage 06 tests."""

from __future__ import annotations

import copy

from ringsentinel.ai.facts import CaseFacts

TS = "2022-09-04T07:13:00"


def make_edge(src, dst, n, total, first="2022-09-04T07:13:00", last="2022-09-05T08:11:00"):
    return {
        "src": src, "dst": dst, "n_transfers": n, "total_inr": float(total),
        "first_ts": first, "last_ts": last,
    }  # fmt: skip


def make_case(
    edges, *, ring_id="R-0123456789ab", score=0.8, rank=1, members=None, n_members=None,
    n_transfers=None, amount=None, oversized=False, members_truncated=False,
    edges_available=True, edges_truncated=False, features=None,
):  # fmt: skip
    nodes = sorted({e["src"] for e in edges} | {e["dst"] for e in edges})
    members = nodes if members is None else members
    total = sum(e["total_inr"] for e in edges) if amount is None else amount
    return {
        "ring_id": ring_id, "rank": rank, "score": score, "expected_value_inr": 1000.0,
        "amount_inr": total, "n_members": len(members) if n_members is None else n_members,
        "n_transfers": sum(e["n_transfers"] for e in edges) if n_transfers is None else n_transfers,
        "oversized": oversized, "members": members, "members_truncated": members_truncated,
        "top_features": features
        if features is not None
        else [{"feature": "burst_share", "mean_contribution": 0.6}],
        "edges": edges, "edges_available": edges_available, "edges_truncated": edges_truncated,
        "ai": {
            "status": "not_built", "built_in_stage": "06", "investigator": None,
            "verifier": None, "benign_explanation": None,
        },
    }  # fmt: skip


S, T1, T2, T3, T4 = "8A0000001", "8B0000002", "8B0000003", "8B0000004", "8B0000005"

# one sender, four receivers
FAN_OUT = [
    make_edge(S, T1, 4, 338392.79, "2022-09-04T07:13:00", "2022-09-06T08:11:00"),
    make_edge(S, T2, 3, 254020.59, "2022-09-04T04:52:00", "2022-09-06T23:44:00"),
    make_edge(S, T3, 2, 100000.00, "2022-09-05T01:00:00", "2022-09-05T02:00:00"),
    make_edge(S, T4, 1, 7564.89, "2022-09-05T09:00:00", "2022-09-05T09:00:00"),
]
A, B, C, D = "8C0000001", "8C0000002", "8C0000003", "8C0000004"
CYCLE = [make_edge(A, B, 2, 5000.0), make_edge(B, C, 2, 4900.0), make_edge(C, A, 1, 4800.0)]
CHAIN = [make_edge(A, B, 1, 900.0), make_edge(B, C, 1, 800.0), make_edge(C, D, 1, 700.0)]


def fan_out_case(**kw):
    return make_case(copy.deepcopy(FAN_OUT), **kw)


def facts(case=None) -> CaseFacts:
    return CaseFacts(case or fan_out_case())


def fan_out_alias_map(case=None) -> dict[str, str]:
    f = facts(case)
    return {n: f.alias(n) for n in sorted(f.nodes)}


def good_case_file_json(f: CaseFacts | None = None) -> dict:
    """A correct final answer for FAN_OUT, written in aliases the way a model would."""
    f = f or facts()
    s = f.alias(S)
    t1 = f.alias(T1)
    return {
        "type": "case_file", "pattern": "fan_out", "suspicion": "high",
        "summary": f"{s} sent money to 4 accounts in 10 transfers.",
        "findings": [
            {
                "text": f"{s} sent to 4 accounts.", "nodes": [s],
                "counts": [{"metric": "out_degree", "account": s, "value": 4}],
                "amounts": [
                    {"metric": "edge_total_inr", "account": s, "counterparty": t1,
                     "value_inr": 338392.79}
                ],
            }
        ],
        "key_accounts": [{"account": s, "role": "source", "reason": "Sends to all others."}],
        "limits": "Only transfers are known.",
        "suggested_checks": ["Check whether the receivers share an owner."],
    }  # fmt: skip


def good_benign_json(f: CaseFacts | None = None, plausibility="medium") -> dict:
    f = f or facts()
    s = f.alias(S)
    return {
        "type": "benign_case", "plausibility": plausibility,
        "summary": "Could be a payout run.",
        "hypotheses": [
            {
                "label": "payroll_or_recurring", "argument": f"{s} may pay 4 people.",
                "nodes": [s], "counts": [{"metric": "out_degree", "account": s, "value": 4}],
                "strength": "medium", "how_to_check": "Compare with payroll records.",
            }
        ],
        "weakest_point": "Amounts differ widely.",
    }  # fmt: skip
