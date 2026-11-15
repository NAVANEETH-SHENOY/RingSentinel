"""Bounded threshold feedback and live queue re-ranking (plan sections 5.7 and 5.9, feature F23).

What it does, in one paragraph. The validation split chose a review threshold (the score above
which a ring is worth an analyst's time). Analysts then decide rings. Every dismissal says "the
detector was too eager here", every confirmation says "it was right". We turn the NET number of
dismissals into a single shift of the threshold in log-odds space, and we bound that shift to a
fixed range. The queue is then re-ranked by expected net value computed from the shifted score.

What it deliberately does NOT do:
  * It never changes a stored score, a rank in the bundle, or a detector. The shift is applied to
    a copy of the score at read time, from the audit log, so it is reproducible and reversible.
  * It never lowers the threshold below the validation-chosen value. Rings under that value are not
    in the bundle, so a lower threshold could not surface anything; only a rise is meaningful.
  * It is not learned and not validated. It is a transparent, bounded heuristic. Whether it helps
    precision is untested, and the interface says so.

The shift is a pure function of three counts and three configuration numbers, so the bounds can
be tested exhaustively (backend/tests/test_stage07_feedback.py).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from ringsentinel.snapshots.export import expected_value_inr

# Hard ceilings. The environment can only choose values at or below these, so a typo in .env can
# never open the bound up. Log-odds units: 1.0 is roughly "odds change by a factor of 2.7".
HARD_MAX_OFFSET = 3.0
HARD_MAX_STEP = 1.0
HARD_MAX_CONFIRM_WEIGHT = 5.0
_EPS = 1e-12

RULE_TEXT = (
    "offset = clamp(step * (dismissed - confirm_weight * confirmed), 0, max_offset), in log-odds. "
    "effective threshold = sigmoid(logit(base threshold) + offset). adjusted score = "
    "sigmoid(logit(score) - offset). Held rings count for nothing. The stored scores never change."
)


@dataclass(frozen=True)
class FeedbackConfig:
    step: float = 0.1
    max_offset: float = 1.5
    confirm_weight: float = 1.0

    def __post_init__(self) -> None:
        for name, value, ceiling in (
            ("step", self.step, HARD_MAX_STEP),
            ("max_offset", self.max_offset, HARD_MAX_OFFSET),
            ("confirm_weight", self.confirm_weight, HARD_MAX_CONFIRM_WEIGHT),
        ):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"{name} must be a number")
            if not math.isfinite(value) or value < 0 or value > ceiling:
                raise ValueError(f"{name} must be between 0 and {ceiling}")


def logit(p: float) -> float:
    p = min(max(float(p), _EPS), 1.0 - _EPS)
    return math.log(p / (1.0 - p))


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def threshold_offset(n_confirmed: int, n_dismissed: int, cfg: FeedbackConfig) -> float:
    """Log-odds shift of the threshold. Always inside [0, cfg.max_offset]."""
    if n_confirmed < 0 or n_dismissed < 0:
        raise ValueError("counts must not be negative")
    raw = cfg.step * (n_dismissed - cfg.confirm_weight * n_confirmed)
    return min(max(raw, 0.0), cfg.max_offset)


def effective_threshold(base: float | None, offset: float) -> float | None:
    """The shifted review threshold in score space (None when the detector flags nothing)."""
    if base is None:
        return None
    if offset == 0.0:
        return base
    return sigmoid(logit(base) + offset)


def adjusted_score(score: float, offset: float) -> float:
    """The score as the live queue sees it. Equal to `score` when the offset is zero."""
    if offset == 0.0:
        return score
    return sigmoid(logit(score) - offset)


def count_decisions(statuses: Mapping[str, str], ring_ids: Iterable[str]) -> dict[str, int]:
    """Latest status per ring, restricted to rings in this bundle (others are ignored)."""
    counts = {"pending": 0, "held": 0, "confirmed": 0, "dismissed": 0}
    for rid in ring_ids:
        counts[statuses.get(rid, "pending")] += 1
    return counts


def _is_open(status: str) -> bool:
    return status in ("pending", "held")


def annotate(
    items: list[dict], statuses: Mapping[str, str], base_threshold: float | None,
    cost: Mapping[str, float], cfg: FeedbackConfig,
) -> tuple[list[dict], dict[str, Any]]:  # fmt: skip
    """Add `status` and `live` to every queue item; return them (in bundle order) and the state.

    `live` = adjusted_score, adjusted_expected_value_inr, above_threshold, live_rank. Only rings
    that are still open (pending or held), above the effective threshold and with a positive
    adjusted value get a live_rank; the rest are listed after them, decided rings last.
    """
    counts = count_decisions(statuses, (i["ring_id"] for i in items))
    offset = threshold_offset(counts["confirmed"], counts["dismissed"], cfg)
    eff = effective_threshold(base_threshold, offset)
    review, fp = cost["review_cost_inr"], cost["fp_cost_inr"]
    capture = cost["loss_capture_rate"]

    rows: list[dict] = []
    for item in items:
        status = statuses.get(item["ring_id"], "pending")
        adj = adjusted_score(item["score"], offset)
        value = expected_value_inr(
            adj, item["amount_inr"], item["n_members"], review, fp, capture
        )
        above = eff is not None and item["score"] >= eff
        rows.append(
            {**item, "status": status, "live": {
                "adjusted_score": adj, "adjusted_expected_value_inr": value,
                "above_threshold": bool(above), "live_rank": None,
            }}  # fmt: skip
        )

    def group(row: dict) -> int:
        if not _is_open(row["status"]):
            return 2
        live = row["live"]
        return 0 if live["above_threshold"] and live["adjusted_expected_value_inr"] > 0 else 1

    order = sorted(
        range(len(rows)),
        key=lambda k: (
            group(rows[k]), -rows[k]["live"]["adjusted_expected_value_inr"], rows[k]["ring_id"]
        ),
    )  # fmt: skip
    rank = 0
    for k in order:
        if group(rows[k]) == 0:
            rank += 1
            rows[k]["live"]["live_rank"] = rank
    rows_live = [rows[k] for k in order]
    state = {
        "base_threshold": base_threshold, "effective_threshold": eff,
        "offset_logit": offset, "max_offset_logit": cfg.max_offset,
        "step_logit": cfg.step, "confirm_weight": cfg.confirm_weight,
        "at_bound": cfg.max_offset > 0 and offset >= cfg.max_offset,
        "n_confirmed": counts["confirmed"], "n_dismissed": counts["dismissed"],
        "n_held": counts["held"], "n_pending": counts["pending"],
        "n_active": rank, "n_deprioritised": sum(1 for r in rows if group(r) == 1),
        "n_in_bundle": len(rows), "rule": RULE_TEXT,
        "validated": False,
        "note": "A heuristic. It is bounded and reversible, but nobody has measured whether it "
        "improves precision.",
    }  # fmt: skip
    return rows_live, state


def export_order(rows_live: list[dict]) -> list[dict]:
    """The same annotated rows in the order the bundle ships (by rank)."""
    return sorted(rows_live, key=lambda r: r["rank"])
