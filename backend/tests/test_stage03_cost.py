"""Guards the rupee cost model arithmetic and the threshold choice."""

from types import SimpleNamespace

import numpy as np
import pytest
from ringsentinel.evaluate.cost import (
    CostParams,
    CostTerms,
    choose_nv_threshold,
    cost_terms,
    net_value,
)
from ringsentinel.evaluate.report import candidate_thresholds


def _ring(members, rows):
    return SimpleNamespace(members=np.array(members), rows=np.array(rows))


def test_cost_terms_hand_case():
    # rows 0..3; rows 0 and 2 are illicit with amounts 100 and 40
    illicit_row = np.array([1, 0, 1, 0])
    amount = np.array([100.0, 7.0, 40.0, 9.0])
    illicit_account = np.array([True, True, False, False, False, True])  # accounts 0..5
    rings = [_ring([0, 1, 2], [0, 1]), _ring([2, 3, 4], [2, 3]), _ring([4, 5], [3])]
    terms = cost_terms(rings, illicit_row, amount, illicit_account)
    assert terms.rings == 3
    assert terms.caught_rings == 2  # the third ring holds only a legitimate transfer
    assert terms.loss_inr == pytest.approx(140.0)
    # distinct accounts {0,1,2,3,4,5}; legitimate (not illicit) ones: 2, 3, 4
    assert terms.legit_accounts == 3


def test_net_value_arithmetic_and_capture_rate():
    terms = CostTerms(rings=4, caught_rings=2, loss_inr=10_000.0, legit_accounts=10)
    params = CostParams(review_cost_inr=250.0, fp_cost_inr=500.0, capture_rate=1.0)
    assert net_value(terms, params) == pytest.approx(10_000 - 4 * 250 - 10 * 500)
    half = CostParams(250.0, 500.0, capture_rate=0.5)
    assert net_value(terms, half) == pytest.approx(5_000 - 1_000 - 5_000)


def test_choose_threshold_takes_the_best_net_value():
    cands = [
        (0.9, CostTerms(1, 1, 1_000.0, 0)),
        (0.5, CostTerms(3, 2, 5_000.0, 2)),
        (0.1, CostTerms(50, 3, 6_000.0, 400)),
    ]
    params = CostParams(250.0, 500.0, 1.0)
    # NV: 750, 5000-750-1000=3250, 6000-12500-200000 < 0
    choice = choose_nv_threshold(cands, params)
    assert choice["threshold"] == 0.5
    assert choice["net_value_inr"] == pytest.approx(3_250.0)
    assert choice["flags_nothing"] is False


def test_choose_threshold_can_decide_to_flag_nothing():
    cands = [(0.5, CostTerms(10, 1, 100.0, 50))]
    choice = choose_nv_threshold(cands, CostParams(250.0, 500.0, 1.0))
    assert choice["flags_nothing"] is True
    assert choice["threshold"] == float("inf")
    assert choice["net_value_inr"] == 0.0


def test_lower_capture_rate_never_flags_more_than_full_capture():
    cands = [
        (0.9, CostTerms(2, 2, 3_000.0, 1)),
        (0.2, CostTerms(30, 5, 4_000.0, 60)),
    ]
    full = choose_nv_threshold(cands, CostParams(100.0, 100.0, 1.0))
    tiny = choose_nv_threshold(cands, CostParams(100.0, 100.0, 0.01))
    assert tiny["threshold"] >= full["threshold"]


def test_equal_net_values_prefer_the_higher_threshold():
    same = CostTerms(1, 1, 1_000.0, 0)
    choice = choose_nv_threshold([(0.2, same), (0.8, same)], CostParams(0.0, 0.0, 1.0))
    assert choice["threshold"] == 0.8


def test_candidate_thresholds_are_descending_and_skip_huge_tie_groups():
    rng = np.random.default_rng(0)
    scores = rng.random(5000)
    grid = candidate_thresholds(scores, positives=10)
    assert grid == sorted(grid, reverse=True) and len(grid) > 5
    ties = np.zeros(100_000)
    ties[:50] = 1.0  # 99,950 rows share the lowest value
    grid2 = candidate_thresholds(ties, positives=5)
    assert 0.0 not in grid2  # flagging at 0.0 would flag everything
    assert candidate_thresholds(np.array([]), positives=1) == []
