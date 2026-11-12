"""Shared metric functions. A transaction is flagged when score >= threshold.

PR-AUC here means average precision: the sum over distinct score thresholds of
(recall_k - recall_{k-1}) * precision_k. With ~0.06 percent positives, compare it with the
prevalence (the score of a random ranking), which is always reported next to it.
"""

from __future__ import annotations

import numpy as np


def _prepare(y_true: np.ndarray, score: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(y_true).astype("int64")
    s = np.asarray(score).astype("float64")
    if y.shape != s.shape or y.ndim != 1:
        raise ValueError("y_true and score must be 1-D arrays of the same length")
    if y.sum() == 0:
        raise ValueError("No positive examples; metrics are undefined")
    return y, s


def precision_recall_f1(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    y = np.asarray(y_true).astype("int64")
    p = np.asarray(y_pred).astype("int64")
    tp = int(((y == 1) & (p == 1)).sum())
    fp = int(((y == 0) & (p == 1)).sum())
    fn = int(((y == 1) & (p == 0)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def _curve(y: np.ndarray, s: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Precision, recall and threshold at each distinct score value (descending)."""
    order = np.argsort(-s, kind="mergesort")
    y_sorted, s_sorted = y[order], s[order]
    tps = np.cumsum(y_sorted)
    fps = np.cumsum(1 - y_sorted)
    last_of_group = np.append(np.where(np.diff(s_sorted) != 0)[0], len(s_sorted) - 1)
    tp, fp = tps[last_of_group], fps[last_of_group]
    precision = tp / (tp + fp)
    recall = tp / y.sum()
    return precision, recall, s_sorted[last_of_group]


def average_precision(y_true: np.ndarray, score: np.ndarray) -> float:
    y, s = _prepare(y_true, score)
    precision, recall, _ = _curve(y, s)
    previous = np.concatenate([[0.0], recall[:-1]])
    return float(np.sum((recall - previous) * precision))


def best_f1_threshold(y_true: np.ndarray, score: np.ndarray) -> tuple[float, float]:
    """Threshold (flag when score >= threshold) that maximizes F1; ties pick the highest."""
    y, s = _prepare(y_true, score)
    precision, recall, thresholds = _curve(y, s)
    denom = precision + recall
    f1 = np.divide(2 * precision * recall, denom, out=np.zeros_like(denom), where=denom > 0)
    best = int(np.argmax(f1))
    return float(thresholds[best]), float(f1[best])


def evaluate_scores(y_true: np.ndarray, score: np.ndarray, threshold: float | None = None) -> dict:
    """Threshold-free PR-AUC plus precision, recall and F1 at a threshold.

    If threshold is None it is chosen to maximize F1 on THIS data, so the reported
    precision, recall and F1 are optimistic ("tuned_on_this_split": True).
    """
    y, s = _prepare(y_true, score)
    tuned = threshold is None
    if tuned:
        threshold, _ = best_f1_threshold(y, s)
    counts = precision_recall_f1(y, (s >= threshold).astype("int64"))
    return {
        "n": int(len(y)),
        "positives": int(y.sum()),
        "prevalence": float(y.mean()),
        "pr_auc": average_precision(y, s),
        "threshold": float(threshold),
        "tuned_on_this_split": tuned,
        "flagged": counts["tp"] + counts["fp"],
        **counts,
    }
