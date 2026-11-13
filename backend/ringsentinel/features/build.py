"""Assemble the feature table for one window (data stage D6).

build_window_features() receives events with ONLY src_account, dst_account, ts and amount_inr
being read. It has no access to labels, ring ids or splits: whatever extra columns a caller
passes are ignored.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ringsentinel.features.community import attach_to_nodes, community_features
from ringsentinel.features.node import node_features
from ringsentinel.graph.build import TransferGraph, build_graph
from ringsentinel.graph.communities import detect_communities

REQUIRED_COLUMNS = ("src_account", "dst_account", "ts", "amount_inr")


def build_window_features(
    events: pd.DataFrame,
    hub_cap: int,
    community_cap: int,
    resolution: float,
    seed: int,
) -> tuple[pd.DataFrame, TransferGraph, np.ndarray, np.ndarray]:
    """Return (per-node feature frame, graph, community ids, oversized flags)."""
    missing = [c for c in REQUIRED_COLUMNS if c not in events.columns]
    if missing:
        raise ValueError(f"events is missing required columns: {missing}")
    graph = build_graph(events[list(REQUIRED_COLUMNS)], hub_cap)
    nodes = node_features(graph)
    kept = graph.und_kept
    community, oversized = detect_communities(
        graph.n, graph.und_a[kept], graph.und_b[kept], graph.und_weight[kept],
        graph.is_hub, community_cap, resolution, seed,
    )  # fmt: skip
    comm_table = community_features(graph, community, oversized, nodes)
    per_node = attach_to_nodes(community, comm_table)
    frame = pd.concat([nodes, per_node], axis=1)
    frame.insert(0, "community_id", community.astype("int32"))
    frame.insert(0, "account", graph.accounts.to_numpy())
    return frame, graph, community, oversized
