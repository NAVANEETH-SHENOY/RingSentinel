"""Guards the tabular features, velocity counts, sampling, design matrices and the test guard."""

import numpy as np
import pandas as pd
import pytest
from ringsentinel.detect.guard import SplitVault, TestSplitAccessError
from ringsentinel.detect.matrix import WindowTable, design_matrix, feature_names, window_table
from ringsentinel.detect.models import (
    ImputedIsolationForest,
    fit_xgb,
    sample_rows,
    score_chunks,
)
from ringsentinel.detect.tabular import TABULAR_COLUMNS, tabular_frame, trailing_counts
from s03_world import make_world


def _brute(group, minutes, window=1440):
    out = []
    for g, m in zip(group, minutes, strict=True):
        out.append(sum(1 for g2, m2 in zip(group, minutes, strict=True)
                       if g2 == g and m - window <= m2 < m))  # fmt: skip
    return np.array(out)


def test_trailing_counts_match_brute_force():
    rng = np.random.default_rng(5)
    group = rng.integers(0, 6, 300)
    minutes = rng.integers(0, 4000, 300)
    assert np.array_equal(trailing_counts(group, minutes), _brute(group, minutes))


def test_trailing_counts_boundaries_and_order_independence():
    group = np.array([1, 1, 1, 1, 2])
    minutes = np.array([0, 1440, 1441, 1441, 1440])
    got = trailing_counts(group, minutes)
    # row1 at 1440 sees minute 0 (window start is inclusive); rows at 1441 see 1440 only,
    # and do not count each other (same minute); group 2 is separate
    assert list(got) == [0, 1, 1, 1, 0]
    perm = np.array([3, 0, 4, 2, 1])
    assert np.array_equal(trailing_counts(group[perm], minutes[perm]), got[perm])
    assert len(trailing_counts(np.array([]), np.array([]))) == 0


def test_tabular_features_ignore_later_events():
    events, _, _ = make_world()
    cut = events["ts"].quantile(0.5)
    early = events[events["ts"] < cut]
    full = tabular_frame(events)
    part = tabular_frame(early)
    assert np.array_equal(full[: len(early)], part)  # events are time-sorted


def test_tabular_columns_and_hand_values():
    events, _, _ = make_world()
    out = tabular_frame(events.head(50))
    assert out.shape == (50, len(TABULAR_COLUMNS)) and out.dtype == np.float32
    assert np.allclose(out[:, 0], np.log1p(events["amount_inr"].head(50).to_numpy()), rtol=1e-5)
    assert set(np.unique(out[:, TABULAR_COLUMNS.index("is_self_transfer")])) <= {0.0, 1.0}


def test_tabular_frame_reports_missing_columns():
    events, _, _ = make_world()
    with pytest.raises(ValueError, match="missing"):
        tabular_frame(events.drop(columns=["payment_format"]))


def test_sample_rows_keeps_every_positive_and_is_seeded():
    y = np.array([0] * 100 + [1] * 5)
    a = sample_rows(y, 0.2, seed=1)
    assert set(np.flatnonzero(y == 1)) <= set(a.tolist())
    assert len(a) == 5 + 20 and np.array_equal(a, np.sort(a))
    assert np.array_equal(a, sample_rows(y, 0.2, seed=1))
    assert not np.array_equal(a, sample_rows(y, 0.2, seed=2))
    assert len(sample_rows(y, 1.0, seed=1)) == 105


def test_design_matrix_hand_case_and_missing_accounts():
    tab = np.arange(8, dtype="float32").reshape(4, 2)
    table = WindowTable(
        accounts=pd.Index(["a", "b"]), values=np.array([[1, 2], [3, 4]], dtype="float32")
    )
    cats = pd.Index(["a", "b", "c"])  # category c is absent from the table
    cat_to_row = table.rows_for(cats)
    src, dst = np.array([0, 1, 2, 0]), np.array([1, 0, 0, 2])
    got = design_matrix(
        np.array([0, 2]), tab, src, dst, table, cat_to_row, use_tabular=True, use_graph=True
    )
    assert got.shape == (2, 2 + 2 + 2)
    assert list(got[0]) == [0, 1, 1, 2, 3, 4]  # row 0: tab, src a, dst b
    assert np.isnan(got[1, 2:4]).all() and list(got[1, 4:]) == [1, 2]  # src c missing
    tab_only = design_matrix(
        np.array([1]), tab, src, dst, None, None, use_tabular=True, use_graph=False
    )
    assert list(tab_only[0]) == [2, 3]
    with pytest.raises(ValueError):
        design_matrix(np.array([0]), tab, src, dst, None, None, use_tabular=False, use_graph=True)


def test_feature_names_and_window_table_validation():
    assert feature_names(["x"], True, True)[-2:] == ["src_x", "dst_x"]
    with pytest.raises(ValueError):
        feature_names(["x"], False, False)
    frame = pd.DataFrame({"window": ["train", "train"], "account": ["a", "a"], "x": [1.0, 2.0]})
    with pytest.raises(ValueError, match="Duplicate"):
        window_table(frame, "train", ["x"])
    with pytest.raises(ValueError, match="No feature rows"):
        window_table(frame, "val", ["x"])


def test_vault_hides_test_and_releases_it_once_per_detector():
    calls = []
    vault = SplitVault({"train": 1, "val": 2}, test_loader=lambda: calls.append("t") or "TEST")
    assert "test" not in vault.fit_view() and calls == []
    assert vault.release_test("a") == "TEST"
    assert vault.release_test("b") == "TEST"
    with pytest.raises(TestSplitAccessError):
        vault.release_test("a")
    assert vault.released == {"a", "b"}
    with pytest.raises(TestSplitAccessError):
        SplitVault({"train": 1, "test": 3}, test_loader=lambda: None)


def test_fit_needs_both_classes():
    x = np.random.default_rng(0).random((40, 3)).astype("float32")
    y_ok = np.array([0, 1] * 20)
    with pytest.raises(ValueError, match="train"):
        fit_xgb(x, np.zeros(40, int), x, y_ok, seed=1)
    with pytest.raises(ValueError, match="validation"):
        fit_xgb(x, y_ok, x, np.ones(40, int), seed=1)


def test_xgb_is_deterministic_for_a_fixed_seed():
    rng = np.random.default_rng(2)
    x = rng.random((300, 4)).astype("float32")
    y = (x[:, 0] + 0.1 * rng.random(300) > 0.8).astype(int)
    a = fit_xgb(x, y, x, y, seed=3).predict_proba(x)[:, 1]
    b = fit_xgb(x, y, x, y, seed=3).predict_proba(x)[:, 1]
    assert np.array_equal(a, b)


def test_isolation_forest_imputes_nan_is_seeded_and_scores_outliers_higher():
    rng = np.random.default_rng(4)
    x = rng.normal(size=(500, 3)).astype("float32")
    x[::7, 1] = np.nan
    forest = ImputedIsolationForest(seed=9).fit(x)
    probe = np.array([[0, 0, 0], [12, 12, 12]], dtype="float32")
    low, high = forest.predict(probe)
    assert high > low
    assert not np.isnan(forest.predict(x)).any()
    again = ImputedIsolationForest(seed=9).fit(x).predict(probe)
    assert np.array_equal(again, forest.predict(probe))


def test_score_chunks_covers_every_row_in_order():
    out = score_chunks(lambda x: x[:, 0], lambda a, b: np.arange(a, b, dtype="float32")[:, None],
                       n_rows=10, chunk=3)  # fmt: skip
    assert list(out) == list(range(10))
