"""Rupee cost model (plan F7, 5.7).

    NV(theta) = capture * sum(loss of caught rings) - c_review * rings flagged
                - c_fp * legitimate accounts inside flagged rings

A flagged ring is "caught" when it holds at least one flagged transaction whose label is
illicit; loss(r) is the INR amount of those illicit transactions. U_FP counts distinct accounts
in flagged rings that appear in no illicit transaction of the evaluated split. `capture` is the
share of that volume a review could actually stop (1.0 is the plan's literal definition).
Costs are planning assumptions (docs/EVALUATION.md); labels are used only to evaluate.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CostParams:
    review_cost_inr: float
    fp_cost_inr: float
    capture_rate: float = 1.0


@dataclass(frozen=True)
class CostTerms:
    """Quantities that do not depend on the cost parameters (so sweeps are arithmetic)."""

    rings: int
    caught_rings: int
    loss_inr: float
    legit_accounts: int

    def as_dict(self) -> dict:
        return {
            "rings": self.rings, "caught_rings": self.caught_rings,
            "loss_inr": self.loss_inr, "legit_accounts_in_rings": self.legit_accounts,
        }  # fmt: skip


def cost_terms(
    rings: list, illicit_row: np.ndarray, amount_inr: np.ndarray, illicit_account: np.ndarray
) -> CostTerms:
    """rings: objects with .members (account codes) and .rows (row positions).

    illicit_row / amount_inr are aligned with the row positions; illicit_account is a boolean
    vector indexed by account code (True when the account is in any illicit transaction).
    """
    caught = 0
    loss = 0.0
    accounts: list[np.ndarray] = []
    for ring in rings:
        hit = illicit_row[ring.rows].astype(bool)
        if hit.any():
            caught += 1
            loss += float(amount_inr[ring.rows][hit].sum())
        accounts.append(ring.members)
    legit = 0
    if accounts:
        unique = np.unique(np.concatenate(accounts))
        legit = int((~illicit_account[unique]).sum())
    return CostTerms(rings=len(rings), caught_rings=caught, loss_inr=loss, legit_accounts=legit)


def net_value(terms: CostTerms, params: CostParams) -> float:
    return (
        params.capture_rate * terms.loss_inr
        - params.review_cost_inr * terms.rings
        - params.fp_cost_inr * terms.legit_accounts
    )


def choose_nv_threshold(candidates: list[tuple[float, CostTerms]], params: CostParams) -> dict:
    """Pick the score threshold with the highest net value on validation.

    candidates: (threshold, terms) pairs. Flagging nothing has net value 0 and is always an
    option (threshold = inf), so a model that cannot beat its costs is told to flag nothing.
    Ties go to the higher threshold (fewer reviews).
    """
    best_threshold, best_value, best_terms = float("inf"), 0.0, None
    for threshold, terms in sorted(candidates, key=lambda c: -c[0]):
        value = net_value(terms, params)
        if value > best_value:
            best_threshold, best_value, best_terms = threshold, value, terms
    return {
        "threshold": best_threshold, "net_value_inr": best_value,
        "terms": best_terms.as_dict() if best_terms else None,
        "flags_nothing": best_terms is None,
    }  # fmt: skip
