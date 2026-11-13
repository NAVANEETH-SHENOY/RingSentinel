"""Community-level features (plan section 5.4), joined back onto nodes.

Computed per community from the hub-controlled graph only. Hub nodes (community id -1) get NaN.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ringsentinel.features.node import hourly_groups
from ringsentinel.graph.build import TransferGraph

COMMUNITY_COLUMNS = (
    "comm_size", "comm_edges", "comm_density", "comm_mean_weighted_degree",
    "comm_max_weighted_degree", "comm_pagerank_mass", "comm_cycles3",
    "comm_max_out_degree", "comm_max_in_degree", "comm_fan_ratio",
    "comm_burst_share", "comm_amount_concentration", "comm_oversized",
)  # fmt: skip


def community_features(
    g: TransferGraph, community: np.ndarray, oversized: np.ndarray, node_frame: pd.DataFrame
) -> pd.DataFrame:
    """One row per community id (0..k-1)."""
    k = int(community.max()) + 1 if (community >= 0).any() else 0
    out = pd.DataFrame(index=pd.RangeIndex(k))
    live = community >= 0
    size = np.bincount(community[live], minlength=k)
    out["comm_size"] = size

    ka, kb = g.und_a[g.und_kept], g.und_b[g.und_kept]
    inside = (community[ka] == community[kb]) & (community[ka] >= 0)
    edges = np.bincount(community[ka][inside], minlength=k)
    pairs = size * (size - 1) / 2.0
    out["comm_edges"] = edges
    out["comm_density"] = np.divide(edges, pairs, out=np.zeros(k), where=pairs > 0)

    members = pd.DataFrame(
        {
            "c": community[live],
            "wdeg": node_frame["idf_weighted_degree"].to_numpy()[live],
            "pr": node_frame["pagerank"].to_numpy()[live],
            "cyc": node_frame["cycles3"].to_numpy()[live],
        }
    )
    grouped = members.groupby("c", sort=True)
    out["comm_mean_weighted_degree"] = grouped["wdeg"].mean().to_numpy()
    out["comm_max_weighted_degree"] = grouped["wdeg"].max().to_numpy()
    out["comm_pagerank_mass"] = grouped["pr"].sum().to_numpy()
    out["comm_cycles3"] = grouped["cyc"].sum().to_numpy() / 3.0

    cs, cd = community[g.dir_src], community[g.dir_dst]
    internal_pair = g.dir_kept & (cs == cd) & (cs >= 0)
    n = g.n
    int_out = np.bincount(g.dir_src[internal_pair], minlength=n)
    int_in = np.bincount(g.dir_dst[internal_pair], minlength=n)
    per_comm = pd.DataFrame({"c": community[live], "o": int_out[live], "i": int_in[live]})
    max_out = per_comm.groupby("c", sort=True)["o"].max().to_numpy()
    max_in = per_comm.groupby("c", sort=True)["i"].max().to_numpy()
    out["comm_max_out_degree"] = max_out
    out["comm_max_in_degree"] = max_in
    out["comm_fan_ratio"] = (max_out + 1.0) / (max_in + 1.0)

    ce = community[g.ev_src]
    internal_event = (ce == community[g.ev_dst]) & (ce >= 0)
    hourly = hourly_groups(ce[internal_event], g.ev_hour[internal_event],
                           g.ev_amt[internal_event], k)  # fmt: skip
    total = hourly["total_amount"]
    out["comm_burst_share"] = np.divide(
        hourly["max_hour_amount"], total, out=np.zeros(k), where=total > 0
    )

    amt = g.dir_amt[internal_pair]
    comm_total = np.bincount(cs[internal_pair], weights=amt, minlength=k)
    sq = np.bincount(cs[internal_pair], weights=amt**2, minlength=k)
    out["comm_amount_concentration"] = np.divide(
        sq, comm_total**2, out=np.zeros(k), where=comm_total > 0
    )
    out["comm_oversized"] = oversized.astype("int8")
    return out.astype("float32")


def attach_to_nodes(community: np.ndarray, comm_frame: pd.DataFrame) -> pd.DataFrame:
    """Per-node view of the community table (NaN for nodes without a community)."""
    take = np.where(community >= 0, community, 0)
    if len(comm_frame) == 0:
        return pd.DataFrame(
            np.nan, index=pd.RangeIndex(len(community)), columns=list(comm_frame.columns)
        )
    rows = comm_frame.iloc[take].reset_index(drop=True)
    rows.loc[community < 0, :] = np.nan
    return rows
