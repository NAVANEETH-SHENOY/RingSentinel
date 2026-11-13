"""Evaluate one detector on the validation and test splits (data stage D9).

Protocol (docs/EVALUATION.md): every threshold is chosen on validation only; the test split is
then scored once at those fixed thresholds. Labels are used here, and only here, to evaluate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ringsentinel.evaluate.cost import (
    CostParams,
    CostTerms,
    choose_nv_threshold,
    cost_terms,
    net_value,
)
from ringsentinel.evaluate.metrics import (
    average_precision,
    best_f1_threshold,
    precision_recall_f1,
)
from ringsentinel.evaluate.ringmatch import match_rings, ring_metrics
from ringsentinel.rings.extract import Ring, extract_rings

TAUS = (0.3, 0.5, 0.7)
REVIEW_GRID = (100.0, 250.0, 1000.0)
FP_GRID = (100.0, 500.0, 2000.0, 5000.0)
CAPTURE_GRID = (1.0, 0.01, 0.0001)
GRID_POINTS = 28


@dataclass
class SplitCtx:
    """Arrays of one split, aligned row by row. Account values are integer codes."""

    name: str
    event_id: np.ndarray
    minutes: np.ndarray
    src: np.ndarray
    dst: np.ndarray
    amount_inr: np.ndarray
    y: np.ndarray
    ring_id: np.ndarray  # -1 when the row is in no pattern ring
    n_accounts: int
    truth: dict[int, np.ndarray]  # pattern rings of this split: ring id -> account codes
    illicit_account: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        mark = np.zeros(self.n_accounts, dtype=bool)
        bad = self.y == 1
        mark[self.src[bad]] = True
        mark[self.dst[bad]] = True
        self.illicit_account = mark


@dataclass
class ExtractionSettings:
    min_size: int
    cap: int
    resolution: float
    seed: int
    taus: tuple[float, ...] = TAUS


class Scored:
    """A split plus one detector's scores, with cached ring extraction per threshold."""

    def __init__(self, ctx: SplitCtx, scores: np.ndarray, ext: ExtractionSettings) -> None:
        if len(scores) != len(ctx.y):
            raise ValueError("scores must be aligned with the split rows.")
        self.ctx, self.scores, self.ext = ctx, np.asarray(scores, dtype="float64"), ext
        self._rings: dict[float, list[Ring]] = {}
        self._terms: dict[float, CostTerms] = {}

    def rings(self, theta: float) -> list[Ring]:
        if theta not in self._rings:
            c = self.ctx
            self._rings[theta] = extract_rings(
                c.src, c.dst, self.scores, c.amount_inr, self.scores >= theta,
                min_size=self.ext.min_size, cap=self.ext.cap,
                resolution=self.ext.resolution, seed=self.ext.seed,
            )  # fmt: skip
        return self._rings[theta]

    def terms(self, theta: float) -> CostTerms:
        if theta not in self._terms:
            c = self.ctx
            self._terms[theta] = cost_terms(
                self.rings(theta), c.y, c.amount_inr, c.illicit_account
            )
        return self._terms[theta]


def candidate_thresholds(scores: np.ndarray, positives: int, points: int = GRID_POINTS) -> list:
    """Score thresholds that flag roughly 10 .. 50 x positives rows (geometric grid)."""
    scores = np.asarray(scores, dtype="float64")
    n = len(scores)
    if n == 0:
        return []
    max_k = int(min(n, max(2000, 50 * max(positives, 1))))
    lo = min(10, max_k)
    ks = np.unique(np.geomspace(lo, max_k, points).astype("int64"))
    asc = np.sort(scores)
    thetas = np.unique(asc[n - ks])  # the k-th largest score
    flagged = n - np.searchsorted(asc, thetas, side="left")
    keep = flagged <= 10 * max_k  # a threshold inside a huge tie group flags too much
    return [float(t) for t in thetas[keep][::-1]]  # descending


def ring_block(scored: Scored, theta: float) -> dict:
    """Ring-level report at one threshold (strict match on pattern rings, plus cost terms)."""
    c = scored.ctx
    rings = scored.rings(theta)
    members = [r.members for r in rings]
    block = ring_metrics(members, c.truth, scored.ext.taus)
    block["lenient_precision"] = (
        float(np.mean([bool(c.y[r.rows].any()) for r in rings])) if rings else 0.0
    )
    sizes = np.array([len(m) for m in members]) if members else np.zeros(0)
    block["ring_size"] = {
        "median": float(np.median(sizes)) if len(sizes) else 0.0,
        "max": int(sizes.max()) if len(sizes) else 0,
    }
    block["oversized_rings"] = int(sum(r.oversized for r in rings))
    block["flagged_transfers_in_rings"] = int(sum(len(r.rows) for r in rings))
    block["cost_terms"] = scored.terms(theta).as_dict()
    return block


def txn_block(ctx: SplitCtx, scores: np.ndarray, theta: float) -> dict:
    flagged = np.asarray(scores) >= theta
    out = precision_recall_f1(ctx.y, flagged)
    out["threshold"] = theta
    in_ring = (ctx.y == 1) & (ctx.ring_id >= 0)
    unringed = (ctx.y == 1) & (ctx.ring_id < 0)
    out["recall_on_ring_positives"] = float(flagged[in_ring].mean()) if in_ring.any() else None
    out["recall_on_unringed_positives"] = (
        float(flagged[unringed].mean()) if unringed.any() else None
    )
    return out


def ring_pr_points(scored: Scored, positives: int, tau: float) -> dict:
    """Ring precision/recall across a threshold grid and an approximate ring AP."""
    points = []
    for theta in candidate_thresholds(scored.scores, positives):
        rings = scored.rings(theta)
        matched = len(match_rings([r.members for r in rings], scored.ctx.truth, tau))
        points.append(
            {
                "threshold": theta, "rings": len(rings),
                "precision": matched / len(rings) if rings else 0.0,
                "recall": matched / len(scored.ctx.truth) if scored.ctx.truth else 0.0,
            }
        )  # fmt: skip
    ap, last = 0.0, 0.0
    for p in sorted(points, key=lambda q: q["recall"]):
        ap += max(p["recall"] - last, 0.0) * p["precision"]
        last = max(last, p["recall"])
    return {"tau": tau, "points": points, "ring_ap_grid": ap}


def latency_block(scored: Scored, theta: float, all_minutes_sorted: np.ndarray) -> dict:
    """Events between a pattern ring's first event and its first flagged ring transaction.

    Retrospective lower bound: scores use window-level features, so a live system would be
    slower. Real streaming latency is Stage 07.
    """
    c = scored.ctx
    flagged = scored.scores >= theta
    rows = np.flatnonzero(c.ring_id >= 0)
    ring_of_row, minutes = c.ring_id[rows], c.minutes[rows]
    delays_events, delays_minutes, detected = [], [], 0
    for rid in c.truth:
        mine = ring_of_row == rid
        if not mine.any():
            continue
        first = int(minutes[mine].min())
        hit = flagged[rows[mine]]
        if hit.any():
            detected += 1
            when = int(minutes[mine][hit].min())
            lo = np.searchsorted(all_minutes_sorted, first, side="left")
            hi = np.searchsorted(all_minutes_sorted, when, side="left")
            delays_events.append(int(hi - lo))
            delays_minutes.append(when - first)
    total = len(c.truth)

    def pct(values, q):
        return float(np.percentile(values, q)) if values else None

    return {
        "threshold": theta, "truth_rings": total, "rings_with_a_flagged_transfer": detected,
        "share_detected": detected / total if total else 0.0,
        "events_median": pct(delays_events, 50), "events_p90": pct(delays_events, 90),
        "minutes_median": pct(delays_minutes, 50), "minutes_p90": pct(delays_minutes, 90),
        "note": "Retrospective lower bound; features are window-level.",
    }  # fmt: skip


def evaluate_detector(
    val: Scored, test: Scored, params: CostParams, with_ring_curve: bool = True
) -> dict:
    """Full report for one detector. Thresholds come from `val`; `test` is scored once."""
    yv, yt = val.ctx.y, test.ctx.y
    positives_val = int(yv.sum())
    f1_choice = best_f1_threshold(yv, val.scores)
    theta_f1 = f1_choice["threshold"]

    val_grid = candidate_thresholds(val.scores, positives_val)
    candidates = [(t, val.terms(t)) for t in val_grid]
    nv_choice = choose_nv_threshold(candidates, params)
    theta_nv = nv_choice["threshold"]

    report: dict = {
        "val": {
            "pr_auc": average_precision(yv, val.scores), "positives": positives_val,
            "prevalence": float(yv.mean()),
            "at_f1_threshold": txn_block(val.ctx, val.scores, theta_f1),
            "note": "Optimistic: thresholds and early stopping were chosen on this split.",
        },
        "test": {
            "pr_auc": average_precision(yt, test.scores), "positives": int(yt.sum()),
            "prevalence": float(yt.mean()),
            "at_f1_threshold": txn_block(test.ctx, test.scores, theta_f1),
        },
        "thresholds": {"f1": theta_f1, "net_value": theta_nv, "chosen_on": "validation"},
        "operating_points": {},
        "ring_scope": "pattern rings only (about 62 percent of positives belong to a pattern ring)",
    }  # fmt: skip
    for label, theta in (("f1", theta_f1), ("net_value", theta_nv)):
        point: dict = {"threshold": theta}
        for split_name, scored in (("val", val), ("test", test)):
            point[split_name] = ring_block(scored, theta) if np.isfinite(theta) else _empty(scored)
        for split_name, scored in (("val", val), ("test", test)):
            terms = scored.terms(theta) if np.isfinite(theta) else CostTerms(0, 0, 0.0, 0)
            point[split_name]["net_value_inr"] = net_value(terms, params)
        report["operating_points"][label] = point
    report["val_net_value_choice"] = nv_choice
    if with_ring_curve:
        report["test"]["ring_pr_tau_0.5"] = ring_pr_points(test, int(yt.sum()), 0.5)
    return report


def _empty(scored: Scored) -> dict:
    block = ring_metrics([], scored.ctx.truth, scored.ext.taus)
    block.update(
        lenient_precision=0.0, ring_size={"median": 0.0, "max": 0}, oversized_rings=0,
        flagged_transfers_in_rings=0, cost_terms=CostTerms(0, 0, 0.0, 0).as_dict(),
    )  # fmt: skip
    return block


def cost_sweep(val: Scored, test: Scored) -> list[dict]:
    """Choose the net-value threshold on validation for every cost setting; report test."""
    grid = candidate_thresholds(val.scores, int(val.ctx.y.sum()))
    candidates = [(t, val.terms(t)) for t in grid]
    rows = []
    for capture in CAPTURE_GRID:
        for review in REVIEW_GRID:
            for fp in FP_GRID:
                params = CostParams(review, fp, capture)
                choice = choose_nv_threshold(candidates, params)
                theta = choice["threshold"]
                terms = test.terms(theta) if np.isfinite(theta) else CostTerms(0, 0, 0.0, 0)
                rows.append(
                    {
                        "capture_rate": capture, "review_cost_inr": review, "fp_cost_inr": fp,
                        "threshold": theta, "flags_nothing": choice["flags_nothing"],
                        "val_net_value_inr": choice["net_value_inr"],
                        "test_net_value_inr": net_value(terms, params),
                        "test_rings": terms.rings, "test_caught_rings": terms.caught_rings,
                        "test_legit_accounts_in_rings": terms.legit_accounts,
                    }
                )  # fmt: skip
    return rows
