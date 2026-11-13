"""Guards the transaction-level metrics against hand-computed cases and scikit-learn."""

import numpy as np
import pytest
from ringsentinel.evaluate.metrics import (
    average_precision,
    best_f1_threshold,
    pr_curve,
    precision_recall_f1,
)
from sklearn.metrics import average_precision_score


def test_average_precision_hand_case():
    y = np.array([1, 0, 1, 0])
    s = np.array([0.9, 0.8, 0.7, 0.1])
    # precision at the two positives: 1 and 2/3, each worth half the recall
    assert average_precision(y, s) == pytest.approx(0.5 * 1 + 0.5 * (2 / 3))


def test_tied_scores_form_one_threshold():
    assert average_precision(np.array([1, 0]), np.array([0.5, 0.5])) == pytest.approx(0.5)


def test_average_precision_matches_sklearn_with_ties():
    rng = np.random.default_rng(3)
    for _ in range(5):
        y = (rng.random(500) < 0.1).astype(int)
        s = np.round(rng.random(500) + y * 0.4, 1)  # many ties
        assert average_precision(y, s) == pytest.approx(average_precision_score(y, s))


def test_no_positives_gives_zero_and_bad_input_is_rejected():
    assert average_precision(np.zeros(4, dtype=int), np.arange(4.0)) == 0.0
    with pytest.raises(ValueError):
        average_precision(np.array([1, 0]), np.array([np.nan, 0.1]))
    with pytest.raises(ValueError):
        average_precision(np.array([1, 2]), np.array([0.1, 0.2]))
    with pytest.raises(ValueError):
        average_precision(np.array([1, 0, 1]), np.array([0.1, 0.2]))


def test_precision_recall_f1_hand_case_and_zero_division():
    y = np.array([1, 1, 0, 0, 1])
    got = precision_recall_f1(y, np.array([1, 0, 1, 0, 1], dtype=bool))
    assert (got["tp"], got["fp"], got["fn"], got["flagged"]) == (2, 1, 1, 3)
    assert got["precision"] == pytest.approx(2 / 3)
    assert got["recall"] == pytest.approx(2 / 3)
    assert got["f1"] == pytest.approx(2 / 3)
    none = precision_recall_f1(y, np.zeros(5, dtype=bool))
    assert none["precision"] == 0.0 and none["recall"] == 0.0 and none["f1"] == 0.0


def test_best_f1_threshold_hand_case():
    y = np.array([1, 1, 0, 0])
    s = np.array([0.9, 0.8, 0.7, 0.1])
    best = best_f1_threshold(y, s)
    assert best["threshold"] == pytest.approx(0.8)
    assert best["f1"] == pytest.approx(1.0)
    assert best["flagged"] == 2


def test_best_f1_threshold_prefers_fewest_flags_on_ties():
    y = np.array([1, 0, 0])
    s = np.array([0.9, 0.5, 0.1])
    assert best_f1_threshold(y, s)["threshold"] == pytest.approx(0.9)


def test_best_f1_threshold_needs_positives():
    with pytest.raises(ValueError):
        best_f1_threshold(np.zeros(3, dtype=int), np.array([0.1, 0.2, 0.3]))


def test_pr_curve_is_thinned_and_starts_at_the_top_score():
    rng = np.random.default_rng(1)
    y = (rng.random(2000) < 0.05).astype(int)
    points = pr_curve(y, rng.random(2000), max_points=50)
    assert 0 < len(points) <= 50
    assert all(0 <= r <= 1 and 0 <= p <= 1 for r, p in points)
