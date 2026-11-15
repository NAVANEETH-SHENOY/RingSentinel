"""Graph features for Elliptic nodes, built by the SAME Stage 02 code as the IBM harness.

An Elliptic node is one transaction and an edge is a payment flow. The Stage 02 builder is account
based, so each edge becomes one "transfer" between two node identifiers at the pseudo time of the
LATER of its two time steps (an edge exists once both ends do). It gets a dummy amount of 1. The
feature table is then taken per window exactly as for IBM: the train window sees train edges, the
validation window train plus validation edges, the test window all edges.

Because amounts and clock times are dummies here, every Stage 02 column derived from them is
excluded (`GRAPH_COLUMNS` is an allow-list of structure-only columns).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ringsentinel.elliptic.load import EllipticData
from ringsentinel.elliptic.settings import EllipticSettings
from ringsentinel.elliptic.split import assign, step_to_ts
from ringsentinel.features.build import build_window_features
from ringsentinel.graph.build import WINDOW_SPLITS

GRAPH_COLUMNS = (
    "out_deg", "in_deg", "degree", "fan_ratio", "recip_partners", "hub_neighbor_share",
    "mean_neighbor_log_degree", "is_hub", "kept_degree", "idf_weighted_degree", "triangles",
    "cycles3", "pagerank", "comm_size", "comm_edges", "comm_density",
    "comm_mean_weighted_degree", "comm_max_weighted_degree", "comm_pagerank_mass",
    "comm_cycles3", "comm_max_out_degree", "comm_max_in_degree", "comm_fan_ratio",
    "comm_oversized",
)  # fmt: skip
# Columns deliberately left out because they come from the dummy amount or dummy clock.
EXCLUDED_COLUMNS = (
    "out_cnt", "in_cnt", "self_cnt", "out_amt", "in_amt", "flow_ratio", "span_hours",
    "active_hours", "burst_share", "txn_per_active_hour", "comm_burst_share",
    "comm_amount_concentration",
)  # fmt: skip
NO_HUB_CAP = 10**9  # ablation: keep every node (IDF weights still apply)


def edge_table(data: EllipticData, settings: EllipticSettings) -> pd.DataFrame:
    """One row per edge in the shape `build_window_features` reads, plus its split."""
    edge_step = np.maximum(data.step[data.edge_src], data.step[data.edge_dst])
    table = pd.DataFrame(
        {
            "src_account": data.tx_id[data.edge_src],
            "dst_account": data.tx_id[data.edge_dst],
            "ts": step_to_ts(edge_step).to_numpy(),
            "amount_inr": np.ones(len(edge_step), dtype="float64"),
        }
    )
    table["split"] = np.asarray(
        assign(edge_step, settings.train_last_step, settings.val_last_step).astype(str)
    )
    return table


def window_frames(
    data: EllipticData, settings: EllipticSettings, hub_cap: int
) -> dict[str, pd.DataFrame]:
    """Graph feature frame (indexed by txId, GRAPH_COLUMNS only) for train, val and test."""
    edges = edge_table(data, settings)
    core = settings.core
    out: dict[str, pd.DataFrame] = {}
    for window, members in WINDOW_SPLITS.items():
        part = edges[edges["split"].isin(members)]
        if part.empty:
            out[window] = pd.DataFrame(columns=list(GRAPH_COLUMNS))
            continue
        frame, _graph, _community, _oversized = build_window_features(
            part, hub_cap, core.community_cap, core.louvain_resolution, core.seed
        )
        out[window] = frame.set_index("account")[list(GRAPH_COLUMNS)].astype("float32")
    return out


def graph_matrix(
    data: EllipticData, rows: np.ndarray, frame: pd.DataFrame
) -> np.ndarray:
    """float32 (len(rows), len(GRAPH_COLUMNS)); NaN for transactions that touch no edge."""
    found = frame.index.get_indexer(data.tx_id[rows])
    out = np.full((len(rows), len(GRAPH_COLUMNS)), np.nan, dtype="float32")
    present = found >= 0
    if present.any():
        out[present] = frame.to_numpy("float32")[found[present]]
    return out
