"""Hub control: IDF-style edge weights and a degree cap (plan section 5.2).

A node with many distinct counterparties is weak evidence of a coordinated link, so an edge
whose larger endpoint has degree d gets weight 1 / log2(1 + d). Nodes with degree above the
cap are dropped from the graph entirely. For the derived device / IP / VPA-handle attributes
the same formula is applied to the attribute's degree.
"""

from __future__ import annotations

import json

import numpy as np

from ringsentinel.config import DEFAULT_HUB_CAP, Settings

# Candidate caps tried on the validation window (ascending).
HUB_CAP_GRID: tuple[int, ...] = (10, 15, 20, 30, 50, 100, 200, 500, 1000)
# The chosen cap is the smallest one that keeps at least this share of validation ring accounts.
MIN_RING_ACCOUNT_RETENTION = 0.99


def idf_weight(degree: np.ndarray | float) -> np.ndarray:
    """w = 1 / log2(1 + d). Strictly decreasing in d; d = 1 gives 1.0, d = 3 gives 0.5."""
    d = np.asarray(degree, dtype="float64")
    return 1.0 / np.log2(1.0 + d)


def hub_mask(degree: np.ndarray, cap: int) -> np.ndarray:
    """True where the node is a hub (degree strictly above the cap) and must be dropped."""
    return np.asarray(degree) > cap


def choose_hub_cap(
    degree: np.ndarray,
    protected_nodes: np.ndarray,
    grid: tuple[int, ...] = HUB_CAP_GRID,
    min_retention: float = MIN_RING_ACCOUNT_RETENTION,
) -> dict:
    """Pick the smallest cap in the grid that keeps min_retention of the protected nodes.

    protected_nodes are node ids of the validation window's ring accounts. This uses
    validation labels to set ONE hyperparameter; it never touches the test window.
    Returns the full table so the choice can be inspected.
    """
    protected = np.unique(np.asarray(protected_nodes, dtype="int64"))
    rows = []
    chosen = None
    for cap in sorted(grid):
        n_hubs = int((degree > cap).sum())
        if len(protected):
            retention = float((degree[protected] <= cap).mean())
        else:
            retention = 1.0
        rows.append({"cap": int(cap), "hub_nodes": n_hubs, "ring_account_retention": retention})
        if chosen is None and retention >= min_retention:
            chosen = int(cap)
    fallback = chosen is None
    if fallback:
        chosen = int(max(grid))
    return {
        "chosen_cap": chosen,
        "rule": f"smallest cap keeping >= {min_retention:.0%} of validation ring accounts",
        "fallback_to_largest": fallback,
        "n_protected_accounts": int(len(protected)),
        "table": rows,
    }


def effective_hub_cap(settings: Settings) -> int:
    """Explicit setting (RS_HUB_CAP), else the tuned value on disk, else the default."""
    if settings.hub_cap is not None:
        return settings.hub_cap
    path = settings.hub_cap_tuning_path
    if path.exists():
        return int(json.loads(path.read_text(encoding="utf-8"))["chosen_cap"])
    return DEFAULT_HUB_CAP
