"""Replay engine (data stage D11, component C14, feature F20) with ring detection latency (F18).

Replay is a list of "ring lights up" events in time order plus a compact timeline of how busy the
test period was, so the interface can play the period back step by step. For each exported ring:

  first_ts        time of the ring's first flagged transfer
  detected_ts     the moment its flagged transfers first touch `min_size` distinct accounts, i.e.
                  the first time the ring looks like a ring of the size the extractor accepts
  assembly_*      detected_ts - first_ts, in minutes and in test-period events in between
  truth_*         when the ring's transfers carry a ground-truth ring id (the dataset's pattern
                  file), the majority id and that true ring's own first transfer; latency_* is then
                  detected_ts - truth_first_ts (the plan's "events between a ring's first event
                  and the moment it is flagged")

RETROSPECTIVE, NOT LIVE. Scores come from window-level features computed over the whole test
window, so a live system could not have produced them at `detected_ts`. The replay shows when the
ring's flagged transfers happened; it is a demonstration of what an analyst would have seen if the
scores had been available that early, and a lower bound on real latency. The output says so.

Everything except `build_replay_document` is pure and deterministic.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import numpy as np
import pandas as pd

from ringsentinel.config import Settings
from ringsentinel.monitor.drift import window_edges
from ringsentinel.snapshots.bundle import SnapshotError
from ringsentinel.snapshots.schemas import SCHEMA_VERSION

BUILT_IN_STAGE = "07"
MIN_TRUTH_SHARE = 0.5  # a true ring must supply at least this share of a ring's transfers
NS_PER_MINUTE = 60_000_000_000


def _iso(ns: int) -> str:
    return pd.Timestamp(int(ns)).isoformat()


def _pct(values: list[float], q: float) -> float | None:
    return float(np.percentile(values, q)) if values else None


def ring_timing(
    ts_ns: np.ndarray, src: list[str], dst: list[str], event_ids: np.ndarray, min_size: int
) -> tuple[int, int, bool]:  # fmt: skip
    """(first_ns, detected_ns, partial) for one ring's transfers.

    Transfers are walked in (time, event id) order. `partial` is True when the listed transfers
    never reach `min_size` accounts (the export keeps at most 500 transfers per ring); the
    detection time is then the last listed transfer.
    """
    order = np.lexsort((event_ids, ts_ns))
    seen: set[str] = set()
    first = int(ts_ns[order[0]])
    for k in order:
        seen.add(src[k])
        seen.add(dst[k])
        if len(seen) >= min_size:
            return first, int(ts_ns[k]), False
    return first, int(ts_ns[order[-1]]), True


def compute_replay(
    rings: list[dict[str, Any]], ring_events: dict[str, dict[str, Any]],
    test_ts_ns: np.ndarray, truth_first_ns: dict[int, int], *, detector: str,
    threshold: float | None, min_size: int, n_steps: int = 96,
) -> dict[str, Any]:  # fmt: skip
    """Build the replay document.

    rings:        exported rings as dicts with ring_id, rank, score, expected_value_inr,
                  n_members, n_transfers
    ring_events:  ring_id -> {"ts_ns", "src", "dst", "event_id", "truth_id"} (aligned lists/arrays;
                  truth_id entries are ints or -1)
    test_ts_ns:   timestamps of every test-split event (any order)
    truth_first_ns: ground-truth ring id -> its first transfer anywhere in the data
    """
    test_sorted = np.sort(np.asarray(test_ts_ns, dtype="int64"))
    events: list[dict[str, Any]] = []
    transfer_ts: list[int] = []
    detected_ts: list[int] = []
    for ring in rings:
        data = ring_events.get(ring["ring_id"])
        if data is None or len(data["ts_ns"]) == 0:
            continue
        ts = np.asarray(data["ts_ns"], dtype="int64")
        transfer_ts.extend(int(t) for t in ts)
        first, found, partial = ring_timing(
            ts, list(data["src"]), list(data["dst"]), np.asarray(data["event_id"]), min_size
        )  # fmt: skip
        detected_ts.append(found)
        lo = int(np.searchsorted(test_sorted, first, side="left"))
        hi = int(np.searchsorted(test_sorted, found, side="left"))
        entry: dict[str, Any] = {
            "ring_id": ring["ring_id"], "rank": ring["rank"], "score": ring["score"],
            "expected_value_inr": ring["expected_value_inr"], "n_members": ring["n_members"],
            "n_transfers": ring["n_transfers"], "first_ts": _iso(first),
            "detected_ts": _iso(found), "partial": partial,
            "assembly_minutes": (found - first) / NS_PER_MINUTE, "assembly_events": hi - lo,
            "truth_ring_id": None, "truth_share": None, "truth_first_ts": None,
            "latency_minutes": None, "latency_events": None,
        }  # fmt: skip
        truth_ids = [int(t) for t in data["truth_id"] if int(t) >= 0]
        if truth_ids:
            counts = Counter(truth_ids)
            top = max(counts.items(), key=lambda kv: (kv[1], -kv[0]))
            truth_id, truth_hits = top
            share = truth_hits / len(data["truth_id"])
            start = int(truth_first_ns.get(truth_id, -1))
            # Latency against a true ring is only meaningful when that ring supplies most of the
            # transfers and the detection did not come before the true ring even started.
            if truth_id in truth_first_ns and share >= MIN_TRUTH_SHARE and found >= start:
                tlo = int(np.searchsorted(test_sorted, start, side="left"))
                entry.update(
                    truth_ring_id=truth_id, truth_share=share, truth_first_ts=_iso(start),
                    latency_minutes=(found - start) / NS_PER_MINUTE, latency_events=hi - tlo,
                )  # fmt: skip
        events.append(entry)
    events.sort(key=lambda e: (e["detected_ts"], e["ring_id"]))

    if len(test_sorted):
        t0, t1 = int(test_sorted[0]), int(test_sorted[-1])
    else:
        t0 = t1 = 0
    bounds = window_edges(t0, t1, n_steps)

    def bucket(values: np.ndarray) -> list[int]:
        if values.size == 0:
            return [0] * n_steps
        idx = np.clip(np.searchsorted(bounds, values, side="right") - 1, 0, n_steps - 1)
        return np.bincount(idx, minlength=n_steps).astype(int).tolist()

    timeline = {
        "start_ts": _iso(t0), "end_ts": _iso(t1), "n_steps": n_steps,
        "step_minutes": ((t1 - t0) / n_steps) / NS_PER_MINUTE if n_steps else 0.0,
        "events": bucket(test_sorted),
        "ring_transfers": bucket(np.asarray(transfer_ts, dtype="int64")),
        "detected": bucket(np.asarray(detected_ts, dtype="int64")),
    }  # fmt: skip
    assembly_min = [e["assembly_minutes"] for e in events]
    assembly_ev = [e["assembly_events"] for e in events]
    lat_min = [e["latency_minutes"] for e in events if e["latency_minutes"] is not None]
    lat_ev = [e["latency_events"] for e in events if e["latency_events"] is not None]
    summary = {
        "n_rings": len(events), "n_partial": sum(1 for e in events if e["partial"]),
        "n_with_truth": len(lat_min),
        "assembly_minutes_median": _pct(assembly_min, 50),
        "assembly_minutes_p90": _pct(assembly_min, 90),
        "assembly_events_median": _pct(assembly_ev, 50),
        "assembly_events_p90": _pct(assembly_ev, 90),
        "latency_minutes_median": _pct(lat_min, 50), "latency_minutes_p90": _pct(lat_min, 90),
        "latency_events_median": _pct(lat_ev, 50), "latency_events_p90": _pct(lat_ev, 90),
        "n_test_events": int(test_sorted.size),
    }  # fmt: skip
    notes = [
        "Retrospective replay: scores use window-level features computed over the whole test "
        "window, so a live system could not have flagged these rings this early. Treat the "
        "latencies as a lower bound.",
        f"A ring counts as detected when its flagged transfers first touch {min_size} accounts. "
        "'Partial' means the export kept too few transfers to reach that and the last listed "
        "transfer is used.",
        "Latency against the truth needs the dataset's pattern ids. It is filled in only when one "
        f"true ring supplies at least {MIN_TRUTH_SHARE:.0%} of a ring's transfers; otherwise it is "
        "empty. Only the exported rings (the review queue) are replayed.",
    ]
    return {
        "schema_version": SCHEMA_VERSION, "status": "ready", "built_in_stage": BUILT_IN_STAGE,
        "detector": detector, "threshold": threshold, "min_ring_members": min_size,
        "timeline": timeline, "events": events, "summary": summary, "notes": notes,
    }  # fmt: skip


def build_replay_document(
    settings: Settings, kept: list[tuple[str, int, float, dict]], *, detector: str,
    threshold: float | None,
) -> dict[str, Any] | None:  # fmt: skip
    """Read the parquet files and call compute_replay. None if a needed file is missing.

    kept: (ring_id, rank, expected_value_inr, ring dict from rings.json) per exported ring.
    """
    if not (settings.events_path.is_file() and settings.split_path.is_file()):
        return None
    split = pd.read_parquet(settings.split_path, columns=["event_id", "split"])
    base = pd.read_parquet(settings.events_path, columns=["event_id", "ts", "ring_id"])
    test_ids = split.loc[split["split"] == "test", "event_id"]
    test_ts = base.loc[base["event_id"].isin(test_ids), "ts"]
    if test_ts.empty:
        raise SnapshotError("the test split has no events")
    truth = base.dropna(subset=["ring_id"]).groupby("ring_id")["ts"].min()
    truth_first = {
        int(k): int(pd.Timestamp(v).to_datetime64().astype("datetime64[ns]").astype("int64"))
        for k, v in truth.items()
    }  # fmt: skip
    wanted = sorted({int(e) for _, _, _, r in kept for e in r["event_ids"]})
    if wanted:
        cols = ["event_id", "ts", "src_account", "dst_account", "ring_id"]
        frame = pd.read_parquet(
            settings.events_path, columns=cols, filters=[("event_id", "in", wanted)]
        )
        frame = frame.assign(
            src_account=frame["src_account"].astype(str),
            dst_account=frame["dst_account"].astype(str),
        ).set_index("event_id")  # fmt: skip
    else:
        empty = pd.Index([], name="event_id")
        frame = pd.DataFrame(columns=["ts", "src_account", "dst_account", "ring_id"], index=empty)
    ring_events: dict[str, dict[str, Any]] = {}
    rings: list[dict[str, Any]] = []
    for ring_id, rank, value, ring in kept:
        ids = [int(e) for e in ring["event_ids"] if int(e) in frame.index]
        sub = frame.loc[ids]
        ring_events[ring_id] = {
            "ts_ns": sub["ts"].to_numpy("datetime64[ns]").astype("int64"),
            "src": sub["src_account"].tolist(), "dst": sub["dst_account"].tolist(),
            "event_id": np.asarray(ids, dtype="int64"),
            "truth_id": sub["ring_id"].fillna(-1).astype("int64").tolist(),
        }  # fmt: skip
        rings.append({
            "ring_id": ring_id, "rank": rank, "score": ring["score"],
            "expected_value_inr": value, "n_members": ring["n_members"],
            "n_transfers": ring["n_transfers"],
        })  # fmt: skip
    return compute_replay(
        rings, ring_events, test_ts.to_numpy("datetime64[ns]").astype("int64"), truth_first,
        detector=detector, threshold=threshold, min_size=settings.ring_min_size,
        n_steps=settings.replay_steps,
    )  # fmt: skip
