"""Drift monitor (data stage D11, component C13, plan section 5.10, feature F19).

For each time window of the test split, compare the detector's score distribution with a
reference distribution using the population stability index:

    PSI = sum_i (p_i - q_i) * ln(p_i / q_i)

q_i is the share of reference scores in bin i, p_i the share of the window's scores. Bins are the
reference's own quantiles (deciles by default; tied quantiles merge, so skewed scores such as these
simply get fewer bins). A share below EPSILON is raised to EPSILON so an empty bin cannot give an
infinite value. A window with fewer than `min_events` scores gets no PSI at all ("insufficient"),
because PSI on a handful of scores is noise.

Two deliberate departures from the plan, both stated in the output's `notes`:
  * The plan says "compared with the training distribution". Stage 03 keeps scores for the
    validation and test splits only, and scores of rows a model was fitted on are in-sample, which
    would make every window look drifted. The reference is therefore the VALIDATION split.
  * Per-window precision uses the dataset's labels, which an operating system would only get late.
    It is shown because the plan asks for it, not because it could be computed live.

Everything here is pure and deterministic. `build_drift_document` is the only function that reads
files.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ringsentinel.config import Settings
from ringsentinel.snapshots.bundle import SnapshotError
from ringsentinel.snapshots.schemas import SCHEMA_VERSION

EPSILON = 1e-4
BUILT_IN_STAGE = "07"
LEVELS = ("ok", "warn", "alert", "insufficient")


def reference_bins(reference: np.ndarray, n_bins: int) -> np.ndarray:
    """Inner bin edges: reference quantiles with duplicates merged (may be fewer than n_bins-1)."""
    reference = np.asarray(reference, dtype="float64")
    if reference.size == 0:
        raise ValueError("the reference needs at least one score")
    if n_bins < 2:
        raise ValueError("n_bins must be at least 2")
    cuts = np.quantile(reference, np.linspace(0.0, 1.0, n_bins + 1)[1:-1])
    return np.unique(cuts)


def bin_shares(values: np.ndarray, inner_edges: np.ndarray) -> np.ndarray:
    """Share of `values` in each of len(inner_edges)+1 bins (right-closed on the left edge)."""
    values = np.asarray(values, dtype="float64")
    index = np.searchsorted(inner_edges, values, side="right")
    counts = np.bincount(index, minlength=len(inner_edges) + 1)
    return counts / max(values.size, 1)


def psi_from_shares(reference_share: np.ndarray, current_share: np.ndarray) -> float:
    q = np.clip(np.asarray(reference_share, dtype="float64"), EPSILON, None)
    p = np.clip(np.asarray(current_share, dtype="float64"), EPSILON, None)
    return float(np.sum((p - q) * np.log(p / q)))


def psi(reference: np.ndarray, current: np.ndarray, n_bins: int = 10) -> float:
    """PSI of `current` against `reference` with reference-quantile bins."""
    edges = reference_bins(reference, n_bins)
    return psi_from_shares(bin_shares(reference, edges), bin_shares(current, edges))


def classify(value: float | None, warn: float, alert: float) -> str:
    if value is None:
        return "insufficient"
    if value >= alert:
        return "alert"
    if value >= warn:
        return "warn"
    return "ok"


def _iso(ns: int) -> str:
    return pd.Timestamp(int(ns)).isoformat()


def window_edges(t_min: int, t_max: int, n_windows: int) -> np.ndarray:
    """n_windows+1 equal-width boundaries from t_min to t_max (integer nanoseconds).

    Exact integer arithmetic: np.linspace works in float64, which cannot hold nanosecond
    timestamps (about 1.7e18) without losing hundreds of nanoseconds.
    """
    if n_windows < 1:
        raise ValueError("n_windows must be at least 1")
    span = int(t_max) - int(t_min)
    return np.array([int(t_min) + span * k // n_windows for k in range(n_windows + 1)],
                    dtype="int64")  # fmt: skip


def compute_drift(
    reference: np.ndarray, test_scores: np.ndarray, test_ts_ns: np.ndarray,
    test_labels: np.ndarray, threshold: float | None, *, detector: str, n_windows: int = 8,
    n_bins: int = 10, warn_level: float = 0.10, alert_level: float = 0.25,
    min_events: int = 500,
) -> dict[str, Any]:  # fmt: skip
    """Build the drift document from arrays. `test_*` arrays are aligned row by row."""
    test_scores = np.asarray(test_scores, dtype="float64")
    test_ts_ns = np.asarray(test_ts_ns, dtype="int64")
    test_labels = np.asarray(test_labels, dtype="int64")
    if not (len(test_scores) == len(test_ts_ns) == len(test_labels)):
        raise ValueError("test scores, timestamps and labels must have the same length")
    if not 0 < warn_level < alert_level:
        raise ValueError("need 0 < warn_level < alert_level")
    edges = reference_bins(reference, n_bins)
    ref_share = bin_shares(reference, edges)
    n_ref_bins = len(edges) + 1

    windows: list[dict[str, Any]] = []
    if len(test_scores):
        bounds = window_edges(int(test_ts_ns.min()), int(test_ts_ns.max()), n_windows)
        # last window is closed on the right so the final event is counted
        which = np.clip(np.searchsorted(bounds, test_ts_ns, side="right") - 1, 0, n_windows - 1)
        for w in range(n_windows):
            mask = which == w
            n = int(mask.sum())
            row: dict[str, Any] = {
                "index": w, "start_ts": _iso(bounds[w]), "end_ts": _iso(bounds[w + 1]),
                "n_events": n,
            }
            value = None
            if n >= min_events and n_ref_bins >= 2:
                value = psi_from_shares(ref_share, bin_shares(test_scores[mask], edges))
            row["psi"] = value
            row["level"] = classify(value, warn_level, alert_level)
            if n:
                s, y = test_scores[mask], test_labels[mask]
                row["mean_score"] = float(s.mean())
                row["n_positives"] = int(y.sum())
                if threshold is not None:
                    flagged = s >= threshold
                    nf, tp = int(flagged.sum()), int((y[flagged] == 1).sum())
                    row["n_flagged"], row["flagged_rate"] = nf, nf / n
                    row["precision_at_threshold"] = tp / nf if nf else None
                    row["recall_at_threshold"] = tp / int(y.sum()) if y.sum() else None
            windows.append(row)

    scored = [w for w in windows if w["psi"] is not None]
    whole = None
    if len(test_scores) >= min_events and n_ref_bins >= 2:
        whole = psi_from_shares(ref_share, bin_shares(test_scores, edges))
    alerts = [w["index"] for w in windows if w["level"] == "alert"]
    warns = [w["index"] for w in windows if w["level"] == "warn"]
    summary = {
        "n_windows": len(windows), "n_scored": len(scored), "n_alert": len(alerts),
        "n_warn": len(warns), "alert_windows": alerts,
        "max_psi": max((w["psi"] for w in scored), default=None),
        "first_alert_index": alerts[0] if alerts else None, "test_psi": whole,
        "n_reference": int(np.asarray(reference).size), "n_test": int(test_scores.size),
    }  # fmt: skip
    notes = [
        "Reference = the validation split's scores. Scores of training rows were not kept and "
        "would be in-sample; the plan's 'training distribution' is therefore not used.",
        "PSI levels follow a rule of thumb (stable < warn, shift >= alert); they are settings, "
        "not statistical tests.",
        "Per-window precision uses the dataset's labels, which a live system would only learn "
        "late. Windows are equal-width in time, so their sizes differ.",
    ]
    if n_ref_bins < 3:
        notes.append("The reference scores have very few distinct values; PSI is coarse.")
    return {
        "schema_version": SCHEMA_VERSION, "status": "ready", "built_in_stage": BUILT_IN_STAGE,
        "detector": detector, "threshold": threshold,
        "psi_warn_level": warn_level, "psi_alert_level": alert_level,
        "reference": {"split": "val", "n_events": int(np.asarray(reference).size)},
        "bins": {
            "n_bins": n_ref_bins, "inner_edges": [float(e) for e in edges],
            "method": "reference quantiles, tied edges merged", "epsilon": EPSILON,
        },
        "windows": windows, "summary": summary, "notes": notes,
    }  # fmt: skip


def not_built() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION, "status": "not_built",
        "built_in_stage": BUILT_IN_STAGE, "psi_alert_level": None, "windows": [],
    }  # fmt: skip


def build_drift_document(
    settings: Settings, detector: str, threshold: float | None
) -> dict[str, Any] | None:
    """Read scores.parquet and events.parquet; None if either file is missing."""
    if not (settings.scores_path.is_file() and settings.events_path.is_file()):
        return None
    scores = pd.read_parquet(settings.scores_path, columns=["event_id", "split", detector])
    events = pd.read_parquet(settings.events_path, columns=["event_id", "ts", "is_illicit"])
    ref = scores.loc[scores["split"] == "val", detector].to_numpy("float64")
    test = scores.loc[scores["split"] == "test", ["event_id", detector]]
    if ref.size == 0 or test.empty:
        raise SnapshotError("scores.parquet has no validation or no test rows for the detector")
    joined = test.merge(events, on="event_id", how="left", validate="one_to_one")
    if joined["ts"].isna().any():
        raise SnapshotError("some scored test events are missing from events.parquet")
    ts_ns = joined["ts"].to_numpy("datetime64[ns]").astype("int64")
    return compute_drift(
        ref, joined[detector].to_numpy("float64"), ts_ns,
        joined["is_illicit"].to_numpy("int64"), threshold, detector=detector,
        n_windows=settings.drift_windows, n_bins=settings.drift_bins,
        warn_level=settings.psi_warn_level, alert_level=settings.psi_alert_level,
        min_events=settings.drift_min_events,
    )  # fmt: skip
