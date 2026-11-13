"""Temporal split (no leakage, ring assignment) and metric functions (hand-computed cases)."""

import numpy as np
import pandas as pd
import pytest
from ringsentinel.evaluation.metrics import (
    average_precision,
    best_f1_threshold,
    evaluate_scores,
    precision_recall_f1,
)
from ringsentinel.split import SplitError, assign_split, build_split, check_no_overlap, compute_cuts
from sklearn.metrics import average_precision_score


def _events(n=1000):
    ts = pd.Series(pd.date_range("2022-09-01", periods=n, freq="min"))
    illicit = np.arange(n) % 50 == 0
    return pd.DataFrame({"event_id": np.arange(n), "ts": ts, "is_illicit": illicit})


def test_split_has_no_time_overlap_and_expected_sizes():
    ev = _events()
    cuts = compute_cuts(ev["ts"], 0.6, 0.2)
    split = assign_split(ev["ts"], cuts)
    check_no_overlap(ev["ts"], split)
    counts = pd.Series(split).value_counts()
    assert counts["train"] == 600 and counts["val"] == 200 and counts["test"] == 200
    train_max = ev.loc[pd.Series(split) == "train", "ts"].max()
    val_min = ev.loc[pd.Series(split) == "val", "ts"].min()
    assert train_max < val_min


def test_ties_never_straddle_a_cut():
    days = ["2022-09-01"] * 400 + ["2022-09-02"] * 400 + ["2022-09-03"] * 200
    ts = pd.Series(pd.to_datetime(days))
    cuts = compute_cuts(ts, 0.5, 0.3)
    split = assign_split(ts, cuts)
    check_no_overlap(ts, split)  # equal timestamps always land in the same split


def test_split_is_deterministic_and_validates_inputs():
    ev = _events()
    a = assign_split(ev["ts"], compute_cuts(ev["ts"], 0.6, 0.2))
    b = assign_split(ev["ts"], compute_cuts(ev["ts"], 0.6, 0.2))
    assert list(a) == list(b)
    with pytest.raises(SplitError):
        compute_cuts(ev["ts"], 0.9, 0.2)
    with pytest.raises(SplitError):
        compute_cuts(pd.Series(pd.to_datetime(["2022-09-01"] * 20)), 0.5, 0.2)  # empty val window


def test_ring_belongs_to_split_of_its_earliest_event():
    ev = _events()
    rings = pd.DataFrame(
        {
            "ring_id": [1, 2],
            "first_ts": [ev["ts"].iloc[10], ev["ts"].iloc[650]],  # train, val
            "last_ts": [ev["ts"].iloc[900], ev["ts"].iloc[700]],  # spans into test; second stays
        }
    )
    _, rings_out, meta = build_split(ev, rings, 0.6, 0.2)
    assert rings_out["ring_split"].astype(str).tolist() == ["train", "val"]
    assert meta["rings_by_split"] == {"train": 1, "val": 1, "test": 0}
    assert sum(meta["rows"].values()) == 1000


def test_precision_recall_f1_hand_case():
    m = precision_recall_f1(np.array([1, 1, 0, 0, 1]), np.array([1, 0, 1, 0, 1]))
    assert (m["tp"], m["fp"], m["fn"]) == (2, 1, 1)
    assert m["precision"] == pytest.approx(2 / 3) and m["recall"] == pytest.approx(2 / 3)
    assert m["f1"] == pytest.approx(2 / 3)
    zero = precision_recall_f1(np.array([0, 0]), np.array([0, 0]))
    assert zero["precision"] == 0.0 and zero["f1"] == 0.0


def test_average_precision_and_best_threshold_hand_case():
    y = np.array([1, 0, 1, 0])
    s = np.array([0.9, 0.8, 0.7, 0.1])
    # precision/recall at each cut: (1, .5), (.5, .5), (2/3, 1), (.5, 1)
    assert average_precision(y, s) == pytest.approx(0.5 * 1 + 0.5 * (2 / 3))
    threshold, f1 = best_f1_threshold(y, s)
    assert threshold == 0.7 and f1 == pytest.approx(0.8)


def test_average_precision_matches_sklearn_including_ties():
    rng = np.random.default_rng(0)
    y = (rng.random(2000) < 0.05).astype(int)
    s = np.round(rng.random(2000) + y * 0.4, 1)  # coarse scores create many ties
    assert average_precision(y, s) == pytest.approx(average_precision_score(y, s))


def test_evaluate_scores_reports_prevalence_and_tuning_flag():
    y = np.array([1, 0, 1, 0, 0, 0, 0, 0])
    s = np.array([0.9, 0.8, 0.7, 0.1, 0.2, 0.3, 0.05, 0.0])
    tuned = evaluate_scores(y, s)
    assert tuned["prevalence"] == 0.25 and tuned["tuned_on_this_split"] is True
    fixed = evaluate_scores(y, s, threshold=0.75)
    assert fixed["tuned_on_this_split"] is False and fixed["flagged"] == 2


def test_metrics_refuse_data_without_positives():
    with pytest.raises(ValueError, match="No positive"):
        average_precision(np.zeros(5), np.arange(5))
