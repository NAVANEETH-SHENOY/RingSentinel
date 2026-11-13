"""Candidate communities: connected components, then Louvain for oversized ones (plan 5.3).

Components of the hub-controlled graph larger than `cap` are split with Louvain; a piece that
is still larger than `cap` is split again, up to `max_depth` times. Pieces that cannot be split
are kept and flagged as oversized. Hub nodes get community id -1. Everything is seeded and uses
sorted node order, so the result is deterministic.
"""

from __future__ import annotations

import random

import igraph as ig
import numpy as np
import pandas as pd
import scipy.sparse as sp
from scipy.sparse.csgraph import connected_components


def component_labels(n: int, a: np.ndarray, b: np.ndarray) -> tuple[int, np.ndarray]:
    """Connected components of an undirected graph with n nodes and edges (a[i], b[i])."""
    if len(a) == 0:
        return n, np.arange(n)
    adj = sp.coo_matrix((np.ones(len(a), dtype="int8"), (a, b)), shape=(n, n))
    count, labels = connected_components(adj, directed=False)
    return int(count), labels.astype("int64")


def _louvain_parts(nodes, ea, eb, ew, resolution, seed) -> list[np.ndarray]:
    """One Louvain pass (igraph multilevel) over the given nodes and weighted edges.

    igraph is used instead of networkx because networkx's Louvain took over five minutes on
    the real 321k-node component for some node orders, while igraph takes a few seconds and is
    repeatable with a seeded generator.
    """
    order = np.argsort(nodes, kind="stable")
    sorted_nodes = nodes[order]
    local_a = order[np.searchsorted(sorted_nodes, ea)]
    local_b = order[np.searchsorted(sorted_nodes, eb)]
    graph = ig.Graph(n=len(nodes), edges=list(zip(local_a.tolist(), local_b.tolist(), strict=True)))
    ig.set_random_number_generator(random.Random(seed))
    clustering = graph.community_multilevel(weights=ew.tolist(), resolution=resolution)
    membership = np.asarray(clustering.membership, dtype="int64")
    by_part = np.argsort(membership, kind="stable")
    bounds = np.cumsum(np.bincount(membership))[:-1]
    parts = [np.sort(nodes[idx]) for idx in np.split(by_part, bounds)]
    return sorted(parts, key=lambda arr: int(arr[0]))


def _split(nodes, ea, eb, ew, cap, resolution, seed, depth, max_depth):
    """Return a list of (node array, oversized flag)."""
    parts = _louvain_parts(nodes, ea, eb, ew, resolution, seed)
    if len(parts) == 1:
        return [(nodes, len(nodes) > cap)]
    result = []
    for part in parts:
        if len(part) <= cap:
            result.append((part, False))
        elif depth + 1 >= max_depth:
            result.append((part, True))
        else:
            inside = np.zeros(int(nodes.max()) + 1, dtype=bool)
            inside[part] = True
            keep = inside[ea] & inside[eb]
            result.extend(
                _split(part, ea[keep], eb[keep], ew[keep], cap, resolution, seed,
                       depth + 1, max_depth)
            )  # fmt: skip
    return result


def detect_communities(
    n: int,
    a: np.ndarray,
    b: np.ndarray,
    w: np.ndarray,
    is_hub: np.ndarray,
    cap: int,
    resolution: float = 1.0,
    seed: int = 42,
    max_depth: int = 3,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (community id per node, oversized flag per community).

    a, b, w are the KEPT edges (hub edges already removed). Hubs get id -1. Ids are contiguous
    from 0, ordered by the smallest node id in each community.
    """
    _, comp = component_labels(n, a, b)
    sizes = np.bincount(comp, minlength=int(comp.max()) + 1)
    community = comp.copy()
    flagged: set[int] = set()  # temporary ids of oversized pieces
    next_id = int(comp.max()) + 1

    big = np.flatnonzero(sizes > cap)
    if len(big):
        node_order = np.argsort(comp, kind="stable")
        node_comp = comp[node_order]
        edge_comp = comp[a]
        edge_order = np.argsort(edge_comp, kind="stable")
        sorted_edge_comp = edge_comp[edge_order]
        for c in big.tolist():
            lo, hi = np.searchsorted(node_comp, [c, c + 1])
            nodes = node_order[lo:hi]
            elo, ehi = np.searchsorted(sorted_edge_comp, [c, c + 1])
            idx = edge_order[elo:ehi]
            pieces = _split(nodes, a[idx], b[idx], w[idx], cap, resolution, seed, 0, max_depth)
            for piece_nodes, oversized in pieces:
                community[piece_nodes] = next_id
                if oversized:
                    flagged.add(next_id)
                next_id += 1

    community = np.where(is_hub, -1, community)
    live = community >= 0
    dense = np.full(n, -1, dtype="int64")
    codes, uniques = pd.factorize(community[live])  # order of first appearance by node id
    dense[live] = codes
    oversized = np.zeros(len(uniques), dtype=bool)
    if flagged:
        oversized = np.isin(uniques, np.fromiter(flagged, dtype="int64"))
    return dense, oversized
