"""Build the account-level transfer graph for one time window (data stage D5).

Nodes are accounts (identified by the account string alone; the bank is not part of the
identity, see docs/DATA.md). Edges are aggregated transfers. Self-transfers are counted but do
not create edges. Only src_account, dst_account, ts and amount_inr are read: no label, ring id
or split column is ever used here, so the graph cannot leak labels.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ringsentinel.graph.hubs import hub_mask, idf_weight

WINDOW_SPLITS: dict[str, tuple[str, ...]] = {
    "train": ("train",),
    "val": ("train", "val"),
    "test": ("train", "val", "test"),
}
NS_PER_HOUR = 3_600_000_000_000


@dataclass
class TransferGraph:
    """Aggregated transfer graph plus the event arrays needed for node features."""

    accounts: pd.Index  # sorted account strings; position = node id
    hub_cap: int
    degree: np.ndarray  # distinct undirected neighbours (self-transfers excluded)
    is_hub: np.ndarray
    self_cnt: np.ndarray
    # directed pairs
    dir_src: np.ndarray
    dir_dst: np.ndarray
    dir_cnt: np.ndarray
    dir_amt: np.ndarray
    dir_to_und: np.ndarray  # index of the undirected pair each directed pair belongs to
    # undirected pairs (a < b)
    und_a: np.ndarray
    und_b: np.ndarray
    und_cnt: np.ndarray
    und_amt: np.ndarray
    und_weight: np.ndarray
    und_kept: np.ndarray
    # non-self events, in input order
    ev_src: np.ndarray
    ev_dst: np.ndarray
    ev_amt: np.ndarray
    ev_hour: np.ndarray

    @property
    def n(self) -> int:
        return len(self.accounts)

    @property
    def dir_weight(self) -> np.ndarray:
        return self.und_weight[self.dir_to_und]

    @property
    def dir_kept(self) -> np.ndarray:
        return self.und_kept[self.dir_to_und]


def cumulative_events(events: pd.DataFrame, window: str) -> pd.DataFrame:
    """Events of a window: everything up to and including the window's own split."""
    if window not in WINDOW_SPLITS:
        raise ValueError(f"Unknown window {window!r}; choose from {tuple(WINDOW_SPLITS)}")
    return events[events["split"].isin(WINDOW_SPLITS[window])]


def build_graph(events: pd.DataFrame, hub_cap: int) -> TransferGraph:
    """Aggregate events into the transfer graph and apply hub control (IDF weights + cap)."""
    src = events["src_account"].astype(object).reset_index(drop=True)
    dst = events["dst_account"].astype(object).reset_index(drop=True)
    m = len(src)
    codes, uniques = pd.factorize(pd.concat([src, dst], ignore_index=True), sort=True)
    accounts = pd.Index(uniques)
    n = len(accounts)
    s = codes[:m].astype("int64")
    d = codes[m:].astype("int64")
    amt = events["amount_inr"].to_numpy("float64")
    hour = events["ts"].to_numpy("datetime64[ns]").astype("int64") // NS_PER_HOUR

    non_self = s != d
    self_cnt = np.bincount(s[~non_self], minlength=n).astype("int64")
    es, ed, ea, eh = s[non_self], d[non_self], amt[non_self], hour[non_self]

    key = es * n + ed
    ukey, inv = np.unique(key, return_inverse=True)
    dir_src, dir_dst = ukey // n, ukey % n
    dir_cnt = np.bincount(inv, minlength=len(ukey)).astype("int64")
    dir_amt = np.bincount(inv, weights=ea, minlength=len(ukey))

    lo, hi = np.minimum(dir_src, dir_dst), np.maximum(dir_src, dir_dst)
    ukey2, inv2 = np.unique(lo * n + hi, return_inverse=True)
    und_a, und_b = ukey2 // n, ukey2 % n
    und_cnt = np.bincount(inv2, weights=dir_cnt, minlength=len(ukey2)).astype("int64")
    und_amt = np.bincount(inv2, weights=dir_amt, minlength=len(ukey2))

    degree = (np.bincount(und_a, minlength=n) + np.bincount(und_b, minlength=n)).astype("int64")
    is_hub = hub_mask(degree, hub_cap)
    und_weight = idf_weight(np.maximum(degree[und_a], degree[und_b]))
    und_kept = ~(is_hub[und_a] | is_hub[und_b])

    return TransferGraph(
        accounts=accounts, hub_cap=hub_cap, degree=degree, is_hub=is_hub, self_cnt=self_cnt,
        dir_src=dir_src, dir_dst=dir_dst, dir_cnt=dir_cnt, dir_amt=dir_amt, dir_to_und=inv2,
        und_a=und_a, und_b=und_b, und_cnt=und_cnt, und_amt=und_amt,
        und_weight=und_weight, und_kept=und_kept,
        ev_src=es, ev_dst=ed, ev_amt=ea, ev_hour=eh,
    )  # fmt: skip


def pruning_report(graph: TransferGraph, ring_nodes: np.ndarray | None = None) -> dict:
    """What hub control removed. ring_nodes (optional) is for reporting only, never a decision."""
    hubs = np.flatnonzero(graph.is_hub)
    top = hubs[np.argsort(-graph.degree[hubs], kind="stable")][:20]
    n_edges = len(graph.und_a)
    kept = int(graph.und_kept.sum())
    report = {
        "hub_cap": int(graph.hub_cap),
        "accounts": int(graph.n),
        "accounts_with_transfer_edges": int((graph.degree > 0).sum()),
        "undirected_edges": int(n_edges),
        "hub_nodes_dropped": int(len(hubs)),
        "edges_dropped": int(n_edges - kept),
        "edges_kept": kept,
        "share_edges_dropped": float((n_edges - kept) / n_edges) if n_edges else 0.0,
        "transfer_count_share_dropped": float(
            1 - graph.und_cnt[graph.und_kept].sum() / graph.und_cnt.sum()
        )
        if n_edges
        else 0.0,
        "edge_weight_mean_all": float(graph.und_weight.mean()) if n_edges else 0.0,
        "edge_weight_mean_kept": float(graph.und_weight[graph.und_kept].mean()) if kept else 0.0,
        "top_dropped_hubs": [
            {"account": str(graph.accounts[i]), "degree": int(graph.degree[i])} for i in top
        ],
    }
    if ring_nodes is not None:
        ring_nodes = np.unique(np.asarray(ring_nodes, dtype="int64"))
        report["ring_accounts_in_window"] = int(len(ring_nodes))
        report["ring_accounts_dropped_as_hubs"] = int(graph.is_hub[ring_nodes].sum())
    return report
