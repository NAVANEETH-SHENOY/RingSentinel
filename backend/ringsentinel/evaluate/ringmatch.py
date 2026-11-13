"""Ring-level match (plan 5.6): a predicted ring is a true positive when its account set
overlaps a ground-truth ring with Jaccard J(P, G) = |P and G| / |P or G| >= tau.

Matching is one-to-one (greedy by descending Jaccard, ties broken by index) so one real ring
cannot be credited to several predicted pieces. Ground truth exists only for pattern rings
(about 62 percent of HI-Small positives), so every number here is "on pattern rings only".
"""

from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np


def jaccard(a: np.ndarray, b: np.ndarray) -> float:
    """Jaccard similarity of two integer sets (arrays may be unsorted, duplicates ignored)."""
    sa, sb = set(np.asarray(a).tolist()), set(np.asarray(b).tolist())
    union = len(sa | sb)
    return len(sa & sb) / union if union else 0.0


def candidate_pairs(
    predicted: list[np.ndarray], truth: dict[int, np.ndarray], min_jaccard: float
) -> list[tuple[float, int, int]]:
    """All (jaccard, predicted index, truth id) pairs with jaccard >= min_jaccard."""
    holders: dict[int, list[int]] = defaultdict(list)
    for p, members in enumerate(predicted):
        for account in set(np.asarray(members).tolist()):
            holders[account].append(p)
    pairs = []
    pred_sizes = [len(set(np.asarray(m).tolist())) for m in predicted]
    for gid, members in truth.items():
        gset = set(np.asarray(members).tolist())
        counts: Counter = Counter()
        for account in gset:
            counts.update(holders.get(account, ()))
        for p, inter in counts.items():
            j = inter / (pred_sizes[p] + len(gset) - inter)
            if j >= min_jaccard:
                pairs.append((j, p, int(gid)))
    return pairs


def match_rings(
    predicted: list[np.ndarray], truth: dict[int, np.ndarray], tau: float
) -> list[tuple[int, int, float]]:
    """One-to-one greedy matching. Returns (predicted index, truth id, jaccard) triples."""
    pairs = candidate_pairs(predicted, truth, tau)
    pairs.sort(key=lambda t: (-t[0], t[1], t[2]))
    used_pred: set[int] = set()
    used_truth: set[int] = set()
    matches = []
    for j, p, g in pairs:
        if p in used_pred or g in used_truth:
            continue
        used_pred.add(p)
        used_truth.add(g)
        matches.append((p, g, j))
    return matches


def ring_metrics(
    predicted: list[np.ndarray], truth: dict[int, np.ndarray], taus: tuple[float, ...]
) -> dict:
    """Strict ring precision, recall and F1 for each tau, over pattern rings only."""
    out: dict = {"predicted_rings": len(predicted), "truth_rings": len(truth), "by_tau": {}}
    for tau in taus:
        matched = len(match_rings(predicted, truth, tau))
        precision = matched / len(predicted) if predicted else 0.0
        recall = matched / len(truth) if truth else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        out["by_tau"][f"{tau:g}"] = {
            "matched": matched, "precision": precision, "recall": recall, "f1": f1,
        }  # fmt: skip
    return out
