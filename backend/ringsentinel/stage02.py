"""Stage 02 orchestration: noise layer (D3), hub-cap tuning, graph and features (D5, D6).

Windows are cumulative and past-only: train = train events, val = train + val events,
test = train + val + test events. Feature rows for a window are the accounts active in that
window's own split, described by the whole cumulative window graph.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from ringsentinel.config import Settings
from ringsentinel.features.build import REQUIRED_COLUMNS, build_window_features
from ringsentinel.graph.ablation import format_ablation_table, giant_component_rows
from ringsentinel.graph.build import (
    WINDOW_SPLITS,
    build_graph,
    cumulative_events,
    pruning_report,
)
from ringsentinel.graph.communities import component_labels
from ringsentinel.graph.hubs import choose_hub_cap, effective_hub_cap
from ringsentinel.noise import ATTRIBUTE_COLUMNS, attribute_degree, build_noise, independence_report

WINDOWS = tuple(WINDOW_SPLITS)
LABELLED_WINDOWS = ("train", "val")  # labels are used only for reporting, never on test


def _write_json(path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_events(settings: Settings) -> pd.DataFrame:
    """Events joined with their split. ring_id is kept for reporting only."""
    columns = ["event_id", *REQUIRED_COLUMNS, "ring_id"]
    events = pd.read_parquet(settings.events_path, columns=columns)
    split = pd.read_parquet(settings.split_path)
    return events.merge(split, on="event_id", how="left", validate="one_to_one")


def ring_accounts(events: pd.DataFrame, ring_ids: set[int] | None = None) -> dict[int, set[str]]:
    """Accounts of each ring that are visible in `events` (ring_id is not a feature)."""
    rows = events[events["ring_id"].notna()]
    if ring_ids is not None:
        rows = rows[rows["ring_id"].isin(ring_ids)]
    pairs = pd.concat(
        [
            rows[["ring_id", "src_account"]].set_axis(["ring_id", "account"], axis=1),
            rows[["ring_id", "dst_account"]].set_axis(["ring_id", "account"], axis=1),
        ]
    )
    pairs["account"] = pairs["account"].astype(str)
    pairs = pairs.drop_duplicates()
    return {int(k): set(v) for k, v in pairs.groupby("ring_id")["account"]}


def _rings_of_window(settings: Settings, window: str) -> set[int]:
    rings = pd.read_parquet(settings.rings_truth_path)
    return set(rings.loc[rings["ring_split"] == window, "ring_id"].astype(int))


def _ring_node_ids(graph, rings: dict[int, set[str]]) -> np.ndarray:
    accounts = sorted(set().union(*rings.values())) if rings else []
    ids = graph.accounts.get_indexer(accounts)
    return np.unique(ids[ids >= 0])


# ---------------------------------------------------------------- D3
def run_noise(settings: Settings) -> dict:
    columns = ["src_account", "dst_account", "ring_id"]
    events = pd.read_parquet(settings.events_path, columns=columns)
    accounts = pd.unique(
        pd.concat([events["src_account"].astype(str), events["dst_account"].astype(str)])
    )
    noise = build_noise(accounts, settings.seed)
    noise.to_parquet(settings.noise_path, index=False)

    ring_sets = ring_accounts(events).values()
    flagged = set().union(*ring_sets) if ring_sets else set()
    report = {
        "note": "Derived and synthetic. Built from account strings and the seed only.",
        "seed": settings.seed,
        "accounts": int(len(noise)),
        "attributes": {
            c: {
                "distinct_values": int(noise[c].nunique()),
                "max_accounts_sharing_one_value": int(attribute_degree(noise, c).max()),
            }
            for c in ATTRIBUTE_COLUMNS
        },
        "independence_of_ring_membership": independence_report(noise, flagged),
    }
    _write_json(settings.noise_report_path, report)
    return report


# ---------------------------------------------------------------- hub cap
def run_tune(settings: Settings) -> dict:
    events = load_events(settings)
    window = cumulative_events(events, "val")
    graph = build_graph(window[list(REQUIRED_COLUMNS)], hub_cap=10**9)  # degrees only
    rings = ring_accounts(window, _rings_of_window(settings, "val"))
    result = choose_hub_cap(graph.degree, _ring_node_ids(graph, rings))
    result["tuned_on"] = "validation window (train + val events), validation rings only"
    _write_json(settings.hub_cap_tuning_path, result)
    return result


# ---------------------------------------------------------------- D5 + D6
def _community_report(graph, community, oversized, cap, comp_sizes, rings) -> dict:
    live = community >= 0
    sizes = np.bincount(community[live]) if live.any() else np.zeros(0, dtype=int)
    report = {
        "components": int(len(comp_sizes)),
        "giant_component_size": int(comp_sizes.max()),
        "giant_component_fraction_of_all_accounts": float(comp_sizes.max() / graph.n),
        "giant_component_fraction_of_linked_accounts": float(
            comp_sizes.max() / max(int((graph.degree > 0).sum()), 1)
        ),
        "communities": int(len(sizes)),
        "community_size_percentiles": {
            str(p): float(np.percentile(sizes, p)) for p in (50, 90, 99, 100)
        }
        if len(sizes)
        else {},
        "community_cap": int(cap),
        "communities_over_cap": int((sizes > cap).sum()),
        "oversized_flagged": int(oversized.sum()),
        "nodes_in_oversized": int(sizes[oversized].sum()) if len(sizes) else 0,
    }
    if rings is not None:
        scores, whole, over = [], 0, 0
        for members in rings.values():
            ids = graph.accounts.get_indexer(sorted(members))
            ids = ids[ids >= 0]
            comms = community[ids]
            comms = comms[comms >= 0]
            if len(comms) == 0:
                scores.append(0.0)
                continue
            values, counts = np.unique(comms, return_counts=True)
            best = values[counts.argmax()]
            inter = counts.max()
            scores.append(inter / (sizes[best] + len(ids) - inter))
            whole += int(len(values) == 1 and counts[0] == len(ids))
            over += int(oversized[best])
        arr = np.array(scores) if scores else np.zeros(0)
        report["ring_recovery_diagnostic"] = {
            "note": "Best-community Jaccard for the window's own rings. Reporting only. "
            "Low values mean communities cannot serve as ring candidates by themselves.",
            "rings": int(len(arr)),
            "median_jaccard": float(np.median(arr)) if len(arr) else 0.0,
            "share_jaccard_ge_0.5": float((arr >= 0.5).mean()) if len(arr) else 0.0,
            "share_jaccard_ge_0.3": float((arr >= 0.3).mean()) if len(arr) else 0.0,
            "share_all_accounts_in_one_community": whole / max(len(arr), 1),
            "share_best_community_oversized": over / max(len(arr), 1),
        }
    return report


def run_features(settings: Settings, windows: tuple[str, ...] = WINDOWS) -> dict:
    events = load_events(settings)
    hub_cap = effective_hub_cap(settings)
    frames, pruning, communities = [], {}, {}
    for window in windows:
        win = cumulative_events(events, window)
        own = events[events["split"] == window]
        frame, graph, community, oversized = build_window_features(
            win[list(REQUIRED_COLUMNS)], hub_cap, settings.community_cap,
            settings.louvain_resolution, settings.seed,
        )  # fmt: skip

        rings = None
        ring_nodes = None
        if window in LABELLED_WINDOWS:  # reporting only; the test window's labels are not read
            rings = ring_accounts(win, _rings_of_window(settings, window))
            ring_nodes = _ring_node_ids(graph, rings)
        pruning[window] = pruning_report(graph, ring_nodes)

        kept = graph.und_kept
        _, comp = component_labels(graph.n, graph.und_a[kept], graph.und_b[kept])
        comp_sizes = np.bincount(comp)
        communities[window] = _community_report(
            graph, community, oversized, settings.community_cap, comp_sizes, rings
        )

        active = pd.Index(
            pd.unique(pd.concat([own["src_account"].astype(str), own["dst_account"].astype(str)]))
        )
        frame = frame[frame["account"].isin(active)].reset_index(drop=True)
        frame.insert(0, "window", window)
        frames.append(frame)

    features = pd.concat(frames, ignore_index=True)
    features["window"] = pd.Categorical(features["window"], categories=list(WINDOWS))
    features.to_parquet(settings.features_path, index=False)
    _write_json(settings.pruning_report_path, {"hub_cap": hub_cap, "windows": pruning})
    _write_json(settings.community_report_path, communities)
    return {
        "hub_cap": hub_cap,
        "rows": {w: int((features["window"] == w).sum()) for w in windows},
        "columns": len(features.columns),
        "pruning": pruning,
        "communities": communities,
    }


# ---------------------------------------------------------------- ablation
def run_ablation(settings: Settings, windows: tuple[str, ...] = WINDOWS) -> dict:
    events = load_events(settings)
    noise = pd.read_parquet(settings.noise_path)
    hub_cap = effective_hub_cap(settings)
    rows: list[dict] = []
    for window in windows:
        win = cumulative_events(events, window)
        graph = build_graph(win[list(REQUIRED_COLUMNS)], hub_cap)
        ring_nodes = None
        if window in LABELLED_WINDOWS:
            rings = ring_accounts(win, _rings_of_window(settings, window))
            ring_nodes = _ring_node_ids(graph, rings)
        rows.extend(
            giant_component_rows(
                graph, noise, window, settings.attr_cap, settings.community_cap, ring_nodes
            )
        )
    result = {
        "hub_cap": hub_cap,
        "attr_cap": settings.attr_cap,
        "community_cap": settings.community_cap,
        "rows": rows,
    }
    _write_json(settings.ablation_path, result)
    return result


def format_ablation(result: dict) -> str:
    return format_ablation_table(result["rows"])


__all__ = [
    "WINDOWS", "run_noise", "run_tune", "run_features", "run_ablation", "format_ablation",
    "load_events", "ring_accounts",
]  # fmt: skip
