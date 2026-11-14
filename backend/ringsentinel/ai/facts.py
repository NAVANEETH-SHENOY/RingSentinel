"""Ground truth for one case: the ring's own graph, aliases, derived statistics.

`CaseFacts` is built from one entry of `cases.json` (the D12 bundle). It is the only thing the
tools and the verifier read, so a claim is "true" exactly when it can be recomputed from here.

Account aliases (`acct-1`, `acct-2`, ...) are what the language model sees. Real account strings
never enter a prompt, which also removes the main prompt-injection path (an id or name that
contains instructions). Aliases are numbered by transfer volume, ties broken by id, so the same
case always gets the same aliases.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any

DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_ALIAS_PREFIXES = ("acct-", "acctx-", "acctxx-", "acctxxx-")


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    n_transfers: int
    total_inr: float
    first_ts: str
    last_ts: str


def _parse_ts(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


class CaseFacts:
    """Read-only facts about one flagged ring."""

    def __init__(self, case: dict):
        self.case = case
        self.ring_id: str = case["ring_id"]
        self.n_members: int = int(case["n_members"])
        self.n_transfers: int = int(case["n_transfers"])
        self.ring_total_inr: float = float(case["amount_inr"])
        self.score: float = float(case["score"])
        self.oversized: bool = bool(case.get("oversized", False))
        self.members_truncated: bool = bool(case.get("members_truncated", False))
        self.edges_available: bool = bool(case.get("edges_available", False))
        self.edges_truncated: bool = bool(case.get("edges_truncated", False))
        self.top_features: list[dict] = list(case.get("top_features", []))
        self.edges: list[Edge] = [
            Edge(
                str(e["src"]), str(e["dst"]), int(e["n_transfers"]), float(e["total_inr"]),
                str(e["first_ts"]), str(e["last_ts"]),
            )
            for e in case.get("edges", [])
        ]  # fmt: skip
        nodes = {str(m) for m in case.get("members", [])}
        for e in self.edges:
            nodes.update((e.src, e.dst))
        self.nodes: frozenset[str] = frozenset(nodes)
        self._out: dict[str, list[Edge]] = {}
        self._in: dict[str, list[Edge]] = {}
        for e in self.edges:
            self._out.setdefault(e.src, []).append(e)
            self._in.setdefault(e.dst, []).append(e)
        self._edge_index: dict[tuple[str, str], Edge] = {(e.src, e.dst): e for e in self.edges}
        self._assign_aliases()

    # ----------------------------------------------------------------- aliases
    def _assign_aliases(self) -> None:
        volume = {n: 0.0 for n in self.nodes}
        for e in self.edges:
            volume[e.src] += e.total_inr
            volume[e.dst] += e.total_inr
        prefix = next(
            (p for p in _ALIAS_PREFIXES if not any(n.startswith(p) for n in self.nodes)),
            "acctxxxx-",
        )
        self.alias_prefix = prefix
        ordered = sorted(self.nodes, key=lambda n: (-volume[n], n))
        self._alias = {n: f"{prefix}{i}" for i, n in enumerate(ordered, start=1)}
        self._real = {a: n for n, a in self._alias.items()}
        self._alias_re = re.compile(rf"(?<![\w-]){re.escape(prefix)}(\d+)(?![\w-])")

    def alias(self, real: str) -> str:
        return self._alias[real]

    def resolve(self, token: str) -> str | None:
        """Real account for an alias or for a real id of this case; None if unknown."""
        if token in self._real:
            return self._real[token]
        return token if token in self.nodes else None

    def is_alias(self, token: str) -> bool:
        return token in self._real

    def dealias_text(self, text: str) -> str:
        return self._alias_re.sub(lambda m: self._real.get(m.group(0), m.group(0)), text)

    def alias_tokens(self, text: str) -> list[str]:
        """Every alias-shaped token in a text (valid or not)."""
        return [m.group(0) for m in self._alias_re.finditer(text)]

    # --------------------------------------------------------------- coverage
    @property
    def coverage(self) -> str:
        """full / partial / none: how much of the ring the retained edges show."""
        if not self.edges_available or not self.edges:
            return "none"
        if self.edges_truncated or self.members_truncated:
            return "partial"
        return "full"

    # ----------------------------------------------------------------- claims
    def out_edges(self, real: str) -> list[Edge]:
        return self._out.get(real, [])

    def in_edges(self, real: str) -> list[Edge]:
        return self._in.get(real, [])

    def edge(self, src: str, dst: str) -> Edge | None:
        return self._edge_index.get((src, dst))

    def count_value(self, metric: str, account: str | None, other: str | None) -> int | None:
        """The true value of a count metric, or None if the target does not exist."""
        if metric == "n_members":
            return self.n_members
        if metric == "n_transfers":
            return self.n_transfers
        if metric == "n_edges":
            return len(self.edges)
        a = self.resolve(account) if account else None
        if metric in ("out_degree", "in_degree"):
            if a is None:
                return None
            return len(self.out_edges(a) if metric == "out_degree" else self.in_edges(a))
        if metric == "edge_n_transfers":
            b = self.resolve(other) if other else None
            found = self.edge(a, b) if a and b else None
            return found.n_transfers if found else None
        return None

    def amount_value(self, metric: str, account: str | None, other: str | None) -> float | None:
        if metric == "ring_total_inr":
            return self.ring_total_inr
        if metric == "max_edge_inr":
            return max((e.total_inr for e in self.edges), default=None)
        a = self.resolve(account) if account else None
        if metric in ("account_out_inr", "account_in_inr"):
            if a is None:
                return None
            edges = self.out_edges(a) if metric == "account_out_inr" else self.in_edges(a)
            return round(sum(e.total_inr for e in edges), 2)
        if metric == "edge_total_inr":
            b = self.resolve(other) if other else None
            found = self.edge(a, b) if a and b else None
            return found.total_inr if found else None
        return None

    # ------------------------------------------------------------- structure
    def _scc_sizes(self) -> list[int]:
        """Sizes of strongly connected components (iterative Tarjan)."""
        index: dict[str, int] = {}
        low: dict[str, int] = {}
        on_stack: set[str] = set()
        stack: list[str] = []
        sizes: list[int] = []
        counter = 0
        for root in sorted(self._out.keys() | self._in.keys()):
            if root in index:
                continue
            work = [(root, iter(sorted(e.dst for e in self._out.get(root, []))))]
            index[root] = low[root] = counter
            counter += 1
            stack.append(root)
            on_stack.add(root)
            while work:
                node, children = work[-1]
                advanced = False
                for child in children:
                    if child not in index:
                        index[child] = low[child] = counter
                        counter += 1
                        stack.append(child)
                        on_stack.add(child)
                        work.append((child, iter(sorted(e.dst for e in self._out.get(child, [])))))
                        advanced = True
                        break
                    if child in on_stack:
                        low[node] = min(low[node], index[child])
                if advanced:
                    continue
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])
                if low[node] == index[node]:
                    size = 0
                    while True:
                        member = stack.pop()
                        on_stack.discard(member)
                        size += 1
                        if member == node:
                            break
                    sizes.append(size)
        return sizes

    def has_cycle(self) -> bool:
        """A directed cycle through at least three distinct accounts."""
        return any(size >= 3 for size in self._scc_sizes())

    def structural_pattern(self) -> str:
        """Deterministic shape of the retained edges (a hint, checked only as a warning)."""
        if not self.edges:
            return "unclear"
        nodes = set(self._out) | set(self._in)
        outd = {n: len(self._out.get(n, [])) for n in nodes}
        ind = {n: len(self._in.get(n, [])) for n in nodes}
        if self.has_cycle():
            return "cycle"
        hubs = [n for n in nodes if ind[n] >= 2 and outd[n] >= 2]
        for h in hubs:
            if all(h in (e.src, e.dst) for e in self.edges):
                return "gather_scatter"
        sources = [n for n in nodes if ind[n] == 0]
        sinks = [n for n in nodes if outd[n] == 0]
        if len(sources) == 1 and len(sinks) == len(nodes) - 1 and outd[sources[0]] >= 3:
            return "fan_out"
        if len(sinks) == 1 and len(sources) == len(nodes) - 1 and ind[sinks[0]] >= 3:
            return "fan_in"
        if len(self.edges) >= 2 and all(ind[n] <= 1 and outd[n] <= 1 for n in nodes):
            return "chain"
        n = len(nodes)
        if n >= 4 and len(self.edges) / (n * (n - 1)) >= 0.3:
            return "dense_cluster"
        return "other"

    # ------------------------------------------------------------ statistics
    def stats(self) -> dict[str, Any]:
        """Headline statistics of the retained edges, written with aliases."""
        edges = self.edges
        nodes = set(self._out) | set(self._in)
        total_shown = round(sum(e.total_inr for e in edges), 2)
        out = {
            "ring_id": self.ring_id,
            "n_members": self.n_members,
            "n_transfers": self.n_transfers,
            "ring_total_inr": round(self.ring_total_inr, 2),
            "n_edges": len(edges),
            "edges_total_inr": total_shown,
            "n_accounts_in_edges": len(nodes),
            "coverage": self.coverage,
            "oversized": self.oversized,
            "structure": self.structural_pattern(),
        }
        if not edges:
            return out
        outd = {n: len(self._out.get(n, [])) for n in nodes}
        ind = {n: len(self._in.get(n, [])) for n in nodes}
        sent = {n: sum(e.total_inr for e in self._out.get(n, [])) for n in nodes}
        got = {n: sum(e.total_inr for e in self._in.get(n, [])) for n in nodes}
        top_out = min(nodes, key=lambda n: (-outd[n], self._alias[n]))
        top_in = min(nodes, key=lambda n: (-ind[n], self._alias[n]))
        top_send = min(nodes, key=lambda n: (-sent[n], self._alias[n]))
        top_recv = min(nodes, key=lambda n: (-got[n], self._alias[n]))
        pairs = {(e.src, e.dst) for e in edges}
        firsts = [t for t in (_parse_ts(e.first_ts) for e in edges) if t]
        lasts = [t for t in (_parse_ts(e.last_ts) for e in edges) if t]
        by_day: dict[str, float] = {}
        for e in edges:
            by_day[e.first_ts[:10]] = by_day.get(e.first_ts[:10], 0.0) + e.total_inr
        busiest = max(by_day, key=lambda d: (by_day[d], d))
        out.update(
            {
                "density": round(len(edges) / (len(nodes) * (len(nodes) - 1)), 3)
                if len(nodes) > 1 else 0.0,
                "max_out_degree": {"account": self.alias(top_out), "value": outd[top_out]},
                "max_in_degree": {"account": self.alias(top_in), "value": ind[top_in]},
                "n_pure_sources": sum(1 for n in nodes if ind[n] == 0),
                "n_pure_sinks": sum(1 for n in nodes if outd[n] == 0),
                "n_relays": sum(1 for n in nodes if ind[n] > 0 and outd[n] > 0),
                "has_cycle_of_3_or_more": self.has_cycle(),
                "n_reciprocal_pairs": sum(1 for a, b in pairs if a < b and (b, a) in pairs),
                "top_sender": {
                    "account": self.alias(top_send), "out_inr": round(sent[top_send], 2),
                    "share_pct": round(100 * sent[top_send] / total_shown, 1)
                    if total_shown else 0.0,
                },
                "top_receiver": {
                    "account": self.alias(top_recv), "in_inr": round(got[top_recv], 2),
                    "share_pct": round(100 * got[top_recv] / total_shown, 1)
                    if total_shown else 0.0,
                },
                "median_edge_inr": round(statistics.median(e.total_inr for e in edges), 2),
                "largest_edge_inr": max(e.total_inr for e in edges),
                "first_transfer": min(firsts).isoformat() if firsts else None,
                "last_transfer": max(lasts).isoformat() if lasts else None,
                "span_hours": round((max(lasts) - min(firsts)).total_seconds() / 3600, 1)
                if firsts and lasts else None,
                "busiest_day_by_first_transfer": {
                    "date": busiest,
                    "share_pct": round(100 * by_day[busiest] / total_shown, 1)
                    if total_shown else 0.0,
                },
            }
        )  # fmt: skip
        return out

    def top_accounts(self, limit: int = 8) -> list[dict]:
        nodes = set(self._out) | set(self._in)
        rows = []
        for n in nodes:
            out_e, in_e = self.out_edges(n), self.in_edges(n)
            rows.append(
                {
                    "account": self.alias(n), "out_degree": len(out_e), "in_degree": len(in_e),
                    "out_inr": round(sum(e.total_inr for e in out_e), 2),
                    "in_inr": round(sum(e.total_inr for e in in_e), 2),
                }
            )  # fmt: skip
        rows.sort(key=lambda r: (-(r["out_inr"] + r["in_inr"]), r["account"]))
        return rows[:limit]

    # ------------------------------------------------- numbers the prose may use
    def known_numbers(self) -> list[float]:
        """Every number that is true of this case; prose may only use these."""
        values: list[float] = [
            self.n_members, self.n_transfers, self.ring_total_inr, len(self.edges),
            round(self.score, 2),
        ]  # fmt: skip
        values.extend(_flatten_numbers(self.stats()))
        for row in self.top_accounts(limit=50):
            values.extend(v for v in row.values() if isinstance(v, (int, float)))
        for e in self.edges:
            values.extend((e.n_transfers, e.total_inr))
        for f in self.top_features:
            values.append(round(float(f.get("mean_contribution", 0.0)), 2))
        return values

    def known_dates(self) -> set[str]:
        dates = set()
        for e in self.edges:
            dates.add(e.first_ts[:10])
            dates.add(e.last_ts[:10])
        return dates


def _flatten_numbers(obj: Any) -> list[float]:
    out: list[float] = []
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for value in obj.values():
            out.extend(_flatten_numbers(value))
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            out.extend(_flatten_numbers(value))
    return out
