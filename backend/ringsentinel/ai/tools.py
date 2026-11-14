"""The only things the investigator may ask for: four deterministic functions over one ring.

Tool results are small JSON objects that use aliases (`acct-3`), amounts in rupees and ISO
timestamps. They never contain free text from the dataset, so they are not a prompt-injection
path. Output sizes are capped so a free-tier token budget is not exhausted by one call.
"""

from __future__ import annotations

from typing import Any

from ringsentinel.ai.facts import CaseFacts, Edge

MAX_ROWS = 20
TOOL_NAMES = ("get_neighbors", "get_timeline", "edge_weights", "community_stats")

TOOL_HELP = """\
Tools (call one per reply; arguments are plain JSON):
- community_stats: {} -> headline statistics of the ring (counts, degrees, shares, time span).
- edge_weights: {"top_n": 1..20, "by": "total_inr" | "n_transfers"} -> the heaviest edges.
- get_neighbors: {"account": "acct-N", "direction": "out" | "in" | "both", "limit": 1..20}
  -> counterparties of one account with transfer counts and amounts.
- get_timeline: {"account": "acct-N" or null, "limit": 1..20} -> edges in time order, for one
  account or for the whole ring."""


class ToolError(Exception):
    """A bad tool call. The message is sent back to the model so it can correct itself."""


def _edge_row(facts: CaseFacts, e: Edge) -> dict[str, Any]:
    return {
        "from": facts.alias(e.src), "to": facts.alias(e.dst), "n_transfers": e.n_transfers,
        "total_inr": e.total_inr, "first_ts": e.first_ts, "last_ts": e.last_ts,
    }  # fmt: skip


def _int_arg(args: dict, name: str, default: int, low: int, high: int) -> int:
    value = args.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"`{name}` must be an integer between {low} and {high}")
    if not low <= value <= high:
        raise ToolError(f"`{name}` must be between {low} and {high}")
    return value


def _account_arg(facts: CaseFacts, args: dict, name: str = "account") -> str:
    token = args.get(name)
    if not isinstance(token, str) or not facts.is_alias(token):
        raise ToolError(f"`{name}` must be one of the aliases of this ring, such as acct-1")
    return facts.resolve(token)  # type: ignore[return-value]


def _unknown_keys(args: dict, allowed: set[str]) -> None:
    extra = sorted(set(args) - allowed)
    if extra:
        raise ToolError(f"unknown argument(s): {', '.join(extra)}")


class ToolBox:
    """Dispatches validated tool calls over one `CaseFacts`."""

    def __init__(self, facts: CaseFacts):
        self.facts = facts

    def call(self, name: str, args: Any) -> dict[str, Any]:
        if name not in TOOL_NAMES:
            raise ToolError(f"unknown tool {name!r}; allowed tools: {', '.join(TOOL_NAMES)}")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise ToolError("`args` must be a JSON object")
        return getattr(self, f"_{name}")(args)

    # ------------------------------------------------------------------ tools
    def _community_stats(self, args: dict) -> dict[str, Any]:
        _unknown_keys(args, set())
        return self.facts.stats() | {"top_accounts": self.facts.top_accounts()}

    def _edge_weights(self, args: dict) -> dict[str, Any]:
        _unknown_keys(args, {"top_n", "by"})
        top_n = _int_arg(args, "top_n", 10, 1, MAX_ROWS)
        by = args.get("by", "total_inr")
        if by not in ("total_inr", "n_transfers"):
            raise ToolError("`by` must be total_inr or n_transfers")
        ranked = sorted(
            self.facts.edges,
            key=lambda e: (-getattr(e, by), self.facts.alias(e.src), self.facts.alias(e.dst)),
        )
        shown = ranked[:top_n]
        total = sum(e.total_inr for e in self.facts.edges)
        return {
            "by": by, "n_edges": len(ranked), "edges": [_edge_row(self.facts, e) for e in shown],
            "top_share_pct": round(100 * sum(e.total_inr for e in shown) / total, 1)
            if total else 0.0,
            "coverage": self.facts.coverage,
        }  # fmt: skip

    def _get_neighbors(self, args: dict) -> dict[str, Any]:
        _unknown_keys(args, {"account", "direction", "limit"})
        account = _account_arg(self.facts, args)
        direction = args.get("direction", "both")
        if direction not in ("out", "in", "both"):
            raise ToolError("`direction` must be out, in or both")
        limit = _int_arg(args, "limit", 10, 1, MAX_ROWS)
        rows: list[dict[str, Any]] = []
        if direction in ("out", "both"):
            rows.extend({"direction": "out", **_edge_row(self.facts, e)}
                        for e in self.facts.out_edges(account))  # fmt: skip
        if direction in ("in", "both"):
            rows.extend({"direction": "in", **_edge_row(self.facts, e)}
                        for e in self.facts.in_edges(account))  # fmt: skip
        rows.sort(key=lambda r: (-r["total_inr"], r["from"], r["to"], r["direction"]))
        return {
            "account": self.facts.alias(account),
            "out_degree": len(self.facts.out_edges(account)),
            "in_degree": len(self.facts.in_edges(account)),
            "out_inr": self.facts.amount_value("account_out_inr", self.facts.alias(account), None),
            "in_inr": self.facts.amount_value("account_in_inr", self.facts.alias(account), None),
            "rows_total": len(rows), "rows_shown": min(len(rows), limit),
            "neighbors": rows[:limit], "coverage": self.facts.coverage,
        }  # fmt: skip

    def _get_timeline(self, args: dict) -> dict[str, Any]:
        _unknown_keys(args, {"account", "limit"})
        limit = _int_arg(args, "limit", 10, 1, MAX_ROWS)
        if args.get("account") is None:
            edges = list(self.facts.edges)
            who = None
        else:
            account = _account_arg(self.facts, args)
            edges = self.facts.out_edges(account) + self.facts.in_edges(account)
            who = self.facts.alias(account)
        edges.sort(key=lambda e: (e.first_ts, self.facts.alias(e.src), self.facts.alias(e.dst)))
        return {
            "account": who, "n_edges": len(edges), "n_shown": min(len(edges), limit),
            "earliest_first_ts": edges[0].first_ts if edges else None,
            "latest_last_ts": max((e.last_ts for e in edges), default=None),
            "edges_in_time_order": [_edge_row(self.facts, e) for e in edges[:limit]],
            "coverage": self.facts.coverage,
        }  # fmt: skip
