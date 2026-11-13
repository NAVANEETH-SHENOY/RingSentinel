"""Turn flagged transactions into candidate rings (data stage D8).

Stage 02 showed that communities of the whole transfer graph do not recover rings, so rings are
built from the SCORED subgraph instead: the flagged transactions only. Accounts are nodes, each
flagged non-self transfer links its two accounts, connected components are found, and any
component larger than `cap` is split with Louvain (the Stage 02 splitter, seeded). Pieces
smaller than `min_size` accounts are dropped. No label, ring id or split is read here.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ringsentinel.graph.communities import detect_communities


@dataclass
class Ring:
    members: np.ndarray  # sorted account codes
    rows: np.ndarray  # positions (into the caller's arrays) of the flagged transfers inside
    score: float  # mean score of those transfers
    amount_inr: float  # total INR amount of those transfers
    oversized: bool = False  # Louvain could not bring it under the cap


def extract_rings(
    src: np.ndarray,
    dst: np.ndarray,
    score: np.ndarray,
    amount_inr: np.ndarray,
    flagged: np.ndarray,
    *,
    min_size: int,
    cap: int,
    resolution: float = 1.0,
    seed: int = 42,
) -> list[Ring]:
    """Rings from the flagged rows. All arrays are aligned; src/dst are integer account codes."""
    sel = np.flatnonzero(np.asarray(flagged, dtype=bool) & (src != dst))
    if len(sel) == 0:
        return []
    s, d = src[sel].astype("int64"), dst[sel].astype("int64")
    nodes, inverse = np.unique(np.concatenate([s, d]), return_inverse=True)
    ls, ld = inverse[: len(sel)], inverse[len(sel) :]
    n = len(nodes)

    lo, hi = np.minimum(ls, ld), np.maximum(ls, ld)
    pair_key, pair_inv = np.unique(lo * n + hi, return_inverse=True)
    weight = np.bincount(pair_inv, weights=score[sel].astype("float64"), minlength=len(pair_key))
    weight = np.maximum(weight, 1e-12)
    community, oversized = detect_communities(
        n, pair_key // n, pair_key % n, weight, np.zeros(n, dtype=bool), cap, resolution, seed
    )

    inside = community[ls] == community[ld]  # transfers that cross a split are dropped
    rows_all = sel[inside]
    comm_of_row = community[ls[inside]]
    order = np.argsort(comm_of_row, kind="stable")
    rows_sorted, comm_sorted = rows_all[order], comm_of_row[order]
    bounds = np.flatnonzero(np.diff(comm_sorted)) + 1
    rings: list[Ring] = []
    for rows, comm in zip(
        np.split(rows_sorted, bounds), np.split(comm_sorted, bounds), strict=True
    ):
        if len(rows) == 0:
            continue
        members = np.unique(np.concatenate([src[rows], dst[rows]]))
        if len(members) < min_size:
            continue
        rows = np.sort(rows)
        rings.append(
            Ring(
                members=members.astype("int64"),
                rows=rows,
                score=float(score[rows].mean()),
                amount_inr=float(amount_inr[rows].sum()),
                oversized=bool(oversized[int(comm[0])]),
            )
        )
    rings.sort(key=lambda r: (-r.score, int(r.members[0]), len(r.members)))
    return rings
