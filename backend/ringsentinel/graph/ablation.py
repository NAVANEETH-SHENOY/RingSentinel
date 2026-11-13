"""Giant-component ablation: how much does hub control change connectivity?

Four graph variants per window:
  transfer, no control   all transfer edges
  transfer, controlled   hub accounts dropped (degree cap)
  +noise, no control     transfer edges plus every derived attribute link
  +noise, controlled     controlled transfer edges plus links of attributes under the cap
IDF weights change edge weights, not connectivity, so they do not appear here; the cap does.
The derived attributes are synthetic and used only for this robustness check.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ringsentinel.graph.build import TransferGraph
from ringsentinel.graph.communities import component_labels
from ringsentinel.noise import ATTRIBUTE_COLUMNS

VARIANTS = (
    ("transfer_no_control", False, False),
    ("transfer_controlled", True, False),
    ("transfer_plus_noise_no_control", False, True),
    ("transfer_plus_noise_controlled", True, True),
)


def attribute_links(
    g: TransferGraph, noise: pd.DataFrame, attr_cap: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """Return (account ids, attribute node ids, is-over-cap flag per link, n attribute nodes).

    Attribute node ids start at 0; add g.n to place them after the accounts.
    """
    aligned = noise.set_index("account").reindex(g.accounts)
    if aligned[list(ATTRIBUTE_COLUMNS)].isna().any().any():
        raise ValueError("noise table is missing accounts that appear in the graph")
    acct_parts, attr_parts, over_parts = [], [], []
    offset = 0
    for column in ATTRIBUTE_COLUMNS:
        codes, uniques = pd.factorize(aligned[column])
        degree = np.bincount(codes, minlength=len(uniques))
        acct_parts.append(np.arange(g.n))
        attr_parts.append(offset + codes)
        over_parts.append(degree[codes] > attr_cap)
        offset += len(uniques)
    return (
        np.concatenate(acct_parts), np.concatenate(attr_parts), np.concatenate(over_parts), offset
    )  # fmt: skip


def giant_component_rows(
    g: TransferGraph,
    noise: pd.DataFrame,
    window: str,
    attr_cap: int,
    community_cap: int,
    ring_nodes: np.ndarray | None = None,
) -> list[dict]:
    acct, attr, over, n_attr = attribute_links(g, noise, attr_cap)
    rows = []
    connected = int((g.degree > 0).sum())  # accounts that appear in at least one transfer edge
    for name, controlled, with_noise in VARIANTS:
        keep_edges = g.und_kept if controlled else np.ones(len(g.und_a), dtype=bool)
        a, b = g.und_a[keep_edges], g.und_b[keep_edges]
        n_nodes = g.n
        n_attr_dropped = 0
        if with_noise:
            link_keep = ~over if controlled else np.ones(len(over), dtype=bool)
            if controlled:
                # an attribute value is dropped when any of its links is over the cap
                n_attr_dropped = int(len(np.unique(attr[over])))
            a = np.concatenate([a, acct[link_keep]])
            b = np.concatenate([b, g.n + attr[link_keep]])
            n_nodes = g.n + n_attr
        _, labels = component_labels(n_nodes, a, b)
        counts = np.bincount(labels[: g.n])
        counts = counts[counts > 0]
        giant = int(counts.max())
        row = {
            "window": window,
            "variant": name,
            "hub_control": controlled,
            "derived_attributes": with_noise,
            "accounts": int(g.n),
            "edges": int(len(a)),
            "components": int(len(counts)),
            "giant_size": giant,
            "giant_fraction": giant / g.n,
            "accounts_with_transfer_edges": connected,
            "components_over_community_cap": int((counts > community_cap).sum()),
            "hub_accounts_dropped": int(g.is_hub.sum()) if controlled else 0,
            "attribute_values_dropped": n_attr_dropped,
        }
        if ring_nodes is not None and len(ring_nodes):
            giant_label = np.bincount(labels[: g.n]).argmax()
            in_giant = labels[ring_nodes] == giant_label
            row["ring_accounts"] = int(len(ring_nodes))
            row["ring_accounts_in_giant_share"] = float(in_giant.mean())
        rows.append(row)
    return rows


def format_ablation_table(rows: list[dict]) -> str:
    head = (
        f"{'window':<7}{'variant':<34}{'components':>11}{'giant':>9}{'giant %':>9}"
        f"{'>cap':>6}{'hubs':>6}{'attr drop':>10}"
    )
    lines = [head]
    for r in rows:
        lines.append(
            f"{r['window']:<7}{r['variant']:<34}{r['components']:>11,}{r['giant_size']:>9,}"
            f"{r['giant_fraction']:>9.2%}{r['components_over_community_cap']:>6}"
            f"{r['hub_accounts_dropped']:>6}{r['attribute_values_dropped']:>10}"
        )
    return "\n".join(lines)
