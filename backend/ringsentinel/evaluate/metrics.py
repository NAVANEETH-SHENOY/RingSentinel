"""Transaction-level metrics (plan F6). Pure numpy; cross-checked against scikit-learn in tests.

Scores are "higher means more suspicious". Equal scores form one threshold, so a tie group is
flagged or not flagged as a whole. A flagged row is one with score >= threshold.
"""

from __future__ import annotations

import numpy as np


def _check(y: np.ndarray, s: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(y)
    s = np.asarray(s, dtype="float64")
    if y.shape != s.shape or y.ndim != 1:
        raise ValueError("y and scores must be 1-D arrays of the same length.")
    if np.isnan(s).any():
        raise ValueError("Scores contain NaN.")
    if not np.isin(y, (0, 1)).all():
        raise ValueError("Labels must be 0 or 1.")
    return y.astype("int64"), s


def _curve(y: np.ndarray, s: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Distinct thresholds (descending) with cumulative tp and fp when flagging score >= t."""
    order = np.argsort(-s, kind="stable")
    ys, ss = y[order], s[order]
    tp = np.cumsum(ys)
    fp = np.cumsum(1 - ys)
    last = np.r_[ss[1:] != ss[:-1], True]
    return ss[last], tp[last], fp[last]


def average_precision(y: np.ndarray, s: np.ndarray) -> float:
    """PR-AUC as average precision: sum over thresholds of (recall step) x precision."""
    y, s = _check(y, s)
    positives = int(y.sum())
    if positives == 0 or len(y) == 0:
        return 0.0
    _, tp, fp = _curve(y, s)
    precision = tp / (tp + fp)
    recall = tp / positives
    return float(np.sum(np.diff(np.r_[0.0, recall]) * precision))


def precision_recall_f1(y: np.ndarray, flagged: np.ndarray) -> dict:
    """Counts and rates for a boolean flag vector. Undefined ratios are reported as 0."""
    y = np.asarray(y).astype("int64")
    flagged = np.asarray(flagged, dtype=bool)
    if y.shape != flagged.shape:
        raise ValueError("y and flagged must have the same shape.")
    tp = int((flagged & (y == 1)).sum())
    fp = int((flagged & (y == 0)).sum())
    fn = int((~flagged & (y == 1)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "flagged": tp + fp, "tp": tp, "fp": fp, "fn": fn,
        "precision": precision, "recall": recall, "f1": f1,
    }  # fmt: skip


def best_f1_threshold(y: np.ndarray, s: np.ndarray) -> dict:
    """Threshold with the highest F1 (ties: the highest threshold, i.e. fewest flags)."""
    y, s = _check(y, s)
    positives = int(y.sum())
    if positives == 0:
        raise ValueError("No positive examples: cannot choose an F1 threshold.")
    thresholds, tp, fp = _curve(y, s)
    precision = tp / (tp + fp)
    recall = tp / positives
    denominator = precision + recall
    f1 = np.divide(
        2 * precision * recall, denominator, out=np.zeros(len(tp)), where=denominator > 0
    )
    best = int(np.argmax(f1))  # argmax returns the first maximum = highest threshold
    return {
        "threshold": float(thresholds[best]), "f1": float(f1[best]),
        "precision": float(precision[best]), "recall": float(recall[best]),
        "flagged": int(tp[best] + fp[best]),
    }  # fmt: skip


def pr_curve(y: np.ndarray, s: np.ndarray, max_points: int = 200) -> list[list[float]]:
    """[recall, precision] points for plotting, thinned evenly to at most max_points."""
    y, s = _check(y, s)
    positives = int(y.sum())
    if positives == 0:
        return []
    _, tp, fp = _curve(y, s)
    points = np.column_stack([tp / positives, tp / (tp + fp)])
    if len(points) > max_points:
        keep = np.unique(np.linspace(0, len(points) - 1, max_points).astype("int64"))
        points = points[keep]
    return [[float(r), float(p)] for r, p in points]
