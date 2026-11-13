"""Node features from one window's transfer graph (plan section 5.4, node-level versions).

Everything is computed from the events and graph of the window (all events up to the window's
own end). No label, ring id or split value is read. Graph-structure columns are NaN for hub
nodes, which are not part of the controlled graph.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import scipy.sparse as sp

from ringsentinel.graph.build import TransferGraph

PAGERANK_DAMPING = 0.85
PAGERANK_ITERATIONS = 100
PAGERANK_TOLERANCE = 1e-10

GRAPH_ONLY_COLUMNS = ("kept_degree", "idf_weighted_degree", "triangles", "cycles3", "pagerank")


def hourly_groups(group: np.ndarray, hour: np.ndarray, amount: np.ndarray, n_groups: int) -> dict:
    """Per group: busiest-hour amount, total amount, active hours, first-to-last span (hours)."""
    out = {
        "max_hour_amount": np.zeros(n_groups),
        "total_amount": np.zeros(n_groups),
        "active_hours": np.zeros(n_groups, dtype="int64"),
        "span_hours": np.zeros(n_groups),
    }
    if len(group) == 0:
        return out
    hr = hour - hour.min()
    width = int(hr.max()) + 1
    ukey, inv = np.unique(group.astype("int64") * width + hr, return_inverse=True)
    cell_amount = np.bincount(inv, weights=amount, minlength=len(ukey))
    cell_group, cell_hour = ukey // width, ukey % width
    starts = np.flatnonzero(np.r_[True, cell_group[1:] != cell_group[:-1]])
    ends = np.r_[starts[1:], len(cell_group)]
    present = cell_group[starts]
    out["max_hour_amount"][present] = np.maximum.reduceat(cell_amount, starts)
    out["total_amount"][present] = np.add.reduceat(cell_amount, starts)
    out["active_hours"][present] = ends - starts
    out["span_hours"][present] = cell_hour[ends - 1] - cell_hour[starts]
    return out


def pagerank(n: int, src: np.ndarray, dst: np.ndarray, weight: np.ndarray) -> np.ndarray:
    """Weighted directed PageRank by power iteration, scaled so the mean over nodes is 1."""
    rank = np.full(n, 1.0 / n)
    out_weight = np.bincount(src, weights=weight, minlength=n)
    has_out = out_weight > 0
    transition = sp.csr_matrix((weight, (dst, src)), shape=(n, n))
    for _ in range(PAGERANK_ITERATIONS):
        share = np.zeros(n)
        share[has_out] = rank[has_out] / out_weight[has_out]
        dangling = rank[~has_out].sum()
        new = (1 - PAGERANK_DAMPING) / n + PAGERANK_DAMPING * (transition @ share + dangling / n)
        done = np.abs(new - rank).sum() < PAGERANK_TOLERANCE
        rank = new
        if done:
            break
    return rank * n


def node_features(g: TransferGraph) -> pd.DataFrame:
    """One row per account node of the window graph."""
    n = g.n
    out_cnt = np.bincount(g.ev_src, minlength=n)
    in_cnt = np.bincount(g.ev_dst, minlength=n)
    out_amt = np.bincount(g.ev_src, weights=g.ev_amt, minlength=n)
    in_amt = np.bincount(g.ev_dst, weights=g.ev_amt, minlength=n)
    out_deg = np.bincount(g.dir_src, minlength=n)
    in_deg = np.bincount(g.dir_dst, minlength=n)

    keys = g.dir_src * n + g.dir_dst
    has_reverse = np.isin(g.dir_dst * n + g.dir_src, keys)
    recip = np.bincount(g.dir_src[has_reverse], minlength=n)

    burst = hourly_groups(
        np.concatenate([g.ev_src, g.ev_dst]),
        np.concatenate([g.ev_hour, g.ev_hour]),
        np.concatenate([g.ev_amt, g.ev_amt]),
        n,
    )
    total = burst["total_amount"]
    burst_share = np.divide(burst["max_hour_amount"], total, out=np.zeros(n), where=total > 0)
    active_hours = burst["active_hours"]
    per_hour = np.divide(
        out_cnt + in_cnt, active_hours, out=np.zeros(n), where=active_hours > 0
    )

    deg = np.maximum(g.degree, 1)
    hub_nbr = np.bincount(g.und_a, weights=g.is_hub[g.und_b], minlength=n) + np.bincount(
        g.und_b, weights=g.is_hub[g.und_a], minlength=n
    )
    log_deg = np.log2(1.0 + g.degree)
    nbr_log_deg = np.bincount(g.und_a, weights=log_deg[g.und_b], minlength=n) + np.bincount(
        g.und_b, weights=log_deg[g.und_a], minlength=n
    )

    ka, kb, kw = g.und_a[g.und_kept], g.und_b[g.und_kept], g.und_weight[g.und_kept]
    kept_degree = np.bincount(ka, minlength=n) + np.bincount(kb, minlength=n)
    idf_wdeg = np.bincount(ka, weights=kw, minlength=n) + np.bincount(kb, weights=kw, minlength=n)
    ones = np.ones(len(ka))
    sym = sp.csr_matrix((np.r_[ones, ones], (np.r_[ka, kb], np.r_[kb, ka])), shape=(n, n))
    triangles = np.asarray((sym @ sym).multiply(sym).sum(axis=1)).ravel() / 2.0

    dk = g.dir_kept
    ds, dd = g.dir_src[dk], g.dir_dst[dk]
    directed = sp.csr_matrix((np.ones(len(ds)), (ds, dd)), shape=(n, n))
    cycles3 = np.asarray((directed @ directed).multiply(directed.T.tocsr()).sum(axis=1)).ravel()
    pr = pagerank(n, ds, dd, g.dir_weight[dk])

    frame = pd.DataFrame(
        {
            "out_cnt": out_cnt, "in_cnt": in_cnt, "self_cnt": g.self_cnt,
            "out_amt": out_amt, "in_amt": in_amt,
            "out_deg": out_deg, "in_deg": in_deg, "degree": g.degree,
            "fan_ratio": (out_deg + 1.0) / (in_deg + 1.0),
            "flow_ratio": (out_amt + 1.0) / (in_amt + 1.0),
            "recip_partners": recip,
            "span_hours": burst["span_hours"], "active_hours": active_hours,
            "burst_share": burst_share, "txn_per_active_hour": per_hour,
            "hub_neighbor_share": hub_nbr / deg,
            "mean_neighbor_log_degree": nbr_log_deg / deg,
            "is_hub": g.is_hub.astype("int8"),
            "kept_degree": kept_degree, "idf_weighted_degree": idf_wdeg,
            "triangles": triangles, "cycles3": cycles3, "pagerank": pr,
        }
    )  # fmt: skip
    frame = frame.astype("float32")
    frame.loc[g.is_hub, list(GRAPH_ONLY_COLUMNS)] = np.nan
    int_cols = ["out_cnt", "in_cnt", "self_cnt", "out_deg", "in_deg", "degree", "recip_partners",
                "active_hours", "is_hub"]  # fmt: skip
    frame[int_cols] = frame[int_cols].astype("int32")
    return frame
