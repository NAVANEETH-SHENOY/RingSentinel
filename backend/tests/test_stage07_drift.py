"""Drift monitor (Stage 07, data stage D11): PSI per window, alerts, and the parquet reader."""

import json

import numpy as np
import pandas as pd
import pytest
from ringsentinel.config import Settings
from ringsentinel.monitor.drift import (
    EPSILON,
    bin_shares,
    build_drift_document,
    classify,
    compute_drift,
    psi,
    psi_from_shares,
    reference_bins,
    window_edges,
)
from ringsentinel.snapshots.bundle import SnapshotError, validate_document

DAY = 24 * 3600 * 10**9
T0 = int(pd.Timestamp("2022-09-10").value)


def make_windows(rng, params, n_per, t0=T0):
    """Scores for consecutive equal windows, one Beta(a, b) per window; timestamps inside each."""
    scores, ts = [], []
    for w, (a, b) in enumerate(params):
        scores.append(rng.beta(a, b, n_per))
        ts.append(t0 + w * DAY + np.sort(rng.integers(0, DAY - 1, n_per)))
    s, t = np.concatenate(scores), np.concatenate(ts)
    return s, t, np.zeros(len(s), dtype="int64")


def run(ref, s, t, y, **kw):
    kw.setdefault("detector", "xgb_graph")
    kw.setdefault("n_windows", len(set((t - t.min()) // DAY)))
    return compute_drift(ref, s, t, y, 0.05, **kw)


# --------------------------------------------------------------- the statistic
def test_psi_matches_a_hand_computation():
    # q = (.25, .75), p = (.5, .5): (.5-.25)ln(2) + (.5-.75)ln(2/3) = 0.274653...
    assert psi_from_shares(np.array([0.25, 0.75]), np.array([0.5, 0.5])) == pytest.approx(
        0.25 * np.log(2) + 0.25 * np.log(1.5), rel=1e-12
    )


def test_identical_shares_give_exactly_zero_and_psi_is_symmetric():
    q = np.array([0.1, 0.4, 0.5])
    p = np.array([0.3, 0.3, 0.4])
    assert psi_from_shares(q, q) == 0.0
    assert psi_from_shares(q, p) == pytest.approx(psi_from_shares(p, q))
    assert psi_from_shares(q, p) > 0


def test_empty_bins_are_floored_not_infinite():
    value = psi_from_shares(np.array([0.5, 0.5, 0.0]), np.array([0.0, 0.5, 0.5]))
    assert np.isfinite(value) and value > 0
    expected = 2 * (0.5 - EPSILON) * np.log(0.5 / EPSILON)
    assert value == pytest.approx(expected)


def test_bins_come_from_reference_quantiles_and_cover_every_value():
    ref = np.arange(1000.0)
    edges = reference_bins(ref, 10)
    assert len(edges) == 9 and np.all(np.diff(edges) > 0)
    shares = bin_shares(np.array([-5.0, 0.0, 450.0, 999.0, 5000.0]), edges)
    assert shares.sum() == pytest.approx(1.0) and len(shares) == 10
    assert bin_shares(ref, edges) == pytest.approx(np.full(10, 0.1), abs=0.002)


def test_tied_reference_scores_merge_bins_instead_of_failing():
    ref = np.concatenate([np.zeros(900), np.linspace(0.1, 1.0, 100)])
    edges = reference_bins(ref, 10)
    assert len(edges) < 9 and len(set(edges)) == len(edges)
    assert psi(ref, ref) == 0.0
    all_same = np.full(50, 0.3)
    assert len(reference_bins(all_same, 10)) == 1  # a single cut: two bins, no crash


def test_reference_input_checks():
    with pytest.raises(ValueError):
        reference_bins(np.array([]), 10)
    with pytest.raises(ValueError):
        reference_bins(np.arange(5.0), 1)
    with pytest.raises(ValueError):
        window_edges(0, 10, 0)


def test_classify_levels():
    assert classify(None, 0.1, 0.25) == "insufficient"
    assert [classify(v, 0.1, 0.25) for v in (0.0, 0.099, 0.1, 0.249, 0.25, 3.0)] == [
        "ok", "ok", "warn", "warn", "alert", "alert",
    ]  # fmt: skip


# --------------------------------------------------------------- the plan's two tests
def test_the_alert_fires_on_deliberately_shifted_data():
    rng = np.random.default_rng(11)
    ref = rng.beta(1, 30, 20000)
    normal, shifted = (1, 30), (3, 20)
    s, t, y = make_windows(rng, [normal] * 4 + [shifted] * 4, 3000)
    doc = run(ref, s, t, y)
    levels = [w["level"] for w in doc["windows"]]
    assert levels == ["ok"] * 4 + ["alert"] * 4
    assert doc["summary"]["first_alert_index"] == 4 and doc["summary"]["alert_windows"] == [
        4, 5, 6, 7,
    ]  # fmt: skip
    assert doc["summary"]["n_alert"] == 4 and doc["summary"]["max_psi"] > 1.0
    assert all(w["psi"] < 0.1 for w in doc["windows"][:4])


def test_the_alert_stays_quiet_on_unshifted_data():
    for seed in range(25):
        rng = np.random.default_rng(seed)
        ref = rng.beta(1, 30, 20000)
        s, t, y = make_windows(rng, [(1, 30)] * 8, 2000)
        doc = run(ref, s, t, y)
        assert doc["summary"]["n_alert"] == 0 and doc["summary"]["n_warn"] == 0, seed
        assert doc["summary"]["max_psi"] < 0.05, seed
        assert doc["status"] == "ready"


def test_a_mild_shift_warns_without_alerting():
    rng = np.random.default_rng(5)
    ref = rng.beta(1, 30, 30000)
    s, t, y = make_windows(rng, [(1, 30)] * 3 + [(1.3, 30)] * 3, 6000)
    doc = run(ref, s, t, y)
    assert {w["level"] for w in doc["windows"][3:]} <= {"warn", "alert"}
    assert doc["summary"]["n_warn"] + doc["summary"]["n_alert"] >= 1


# --------------------------------------------------------------- windows and per-window figures
def test_window_counts_add_up_and_the_last_event_is_included():
    rng = np.random.default_rng(2)
    ref = rng.beta(1, 30, 5000)
    s, t, y = make_windows(rng, [(1, 30)] * 4, 700)
    doc = run(ref, s, t, y, n_windows=4)
    assert sum(w["n_events"] for w in doc["windows"]) == len(s)
    assert doc["windows"][0]["start_ts"] == pd.Timestamp(t.min()).isoformat()
    assert doc["windows"][-1]["end_ts"] == pd.Timestamp(t.max()).isoformat()
    assert doc["summary"]["n_test"] == len(s) and doc["summary"]["n_reference"] == 5000


def test_a_small_window_gets_no_psi():
    rng = np.random.default_rng(3)
    ref = rng.beta(1, 30, 5000)
    s, t, y = make_windows(rng, [(1, 30)] * 3, 800)
    keep = np.ones(len(s), dtype=bool)
    keep[800 + 100 :1600] = False  # window 1 keeps only 100 events
    doc = run(ref, s[keep], t[keep], y[keep], n_windows=3, min_events=500)
    assert doc["windows"][1]["psi"] is None and doc["windows"][1]["level"] == "insufficient"
    assert doc["windows"][0]["psi"] is not None
    assert doc["summary"]["n_scored"] == 2 and doc["summary"]["n_windows"] == 3


def test_precision_and_recall_per_window_by_hand():
    ref = np.linspace(0, 1, 1000)
    # one window: scores .9 .8 .1 .1 .7 ; labels 1 0 0 1 1 ; threshold .5 -> flagged 3, tp 2
    s = np.array([0.9, 0.8, 0.1, 0.1, 0.7])
    y = np.array([1, 0, 0, 1, 1])
    t = T0 + np.arange(5) * 60 * 10**9
    doc = compute_drift(ref, s, t, y, 0.5, detector="d", n_windows=1, min_events=1)
    w = doc["windows"][0]
    assert (w["n_events"], w["n_positives"], w["n_flagged"]) == (5, 3, 3)
    assert w["flagged_rate"] == pytest.approx(0.6)
    assert w["precision_at_threshold"] == pytest.approx(2 / 3)
    assert w["recall_at_threshold"] == pytest.approx(2 / 3)
    assert w["mean_score"] == pytest.approx(s.mean())


def test_no_flags_means_precision_is_empty_not_zero_or_nan():
    ref = np.linspace(0, 1, 100)
    t = T0 + np.arange(4) * 10**9
    doc = compute_drift(ref, np.array([0.1] * 4), t, np.zeros(4, int), 0.9, detector="d",
                        n_windows=1, min_events=1)  # fmt: skip
    w = doc["windows"][0]
    assert w["n_flagged"] == 0 and w["precision_at_threshold"] is None
    assert w["recall_at_threshold"] is None
    doc = compute_drift(ref, np.array([0.1] * 4), t, np.zeros(4, int), None, detector="d",
                        n_windows=1, min_events=1)  # fmt: skip
    assert "n_flagged" not in doc["windows"][0] and doc["threshold"] is None


def test_output_is_deterministic_and_json_safe():
    rng = np.random.default_rng(9)
    ref = rng.beta(1, 30, 4000)
    s, t, y = make_windows(rng, [(1, 30)] * 3 + [(3, 20)], 900)
    a, b = run(ref, s, t, y), run(ref, s, t, y)
    dump = {"sort_keys": True, "allow_nan": False}
    assert json.dumps(a, **dump) == json.dumps(b, **dump)
    validate_document("drift.json", a)


def test_bad_inputs_are_refused():
    ref = np.linspace(0, 1, 100)
    with pytest.raises(ValueError, match="same length"):
        compute_drift(ref, np.zeros(3), np.zeros(2, int), np.zeros(3, int), 0.5, detector="d")
    with pytest.raises(ValueError, match="warn_level"):
        compute_drift(ref, np.zeros(3), np.arange(3), np.zeros(3, int), 0.5, detector="d",
                      warn_level=0.3, alert_level=0.2)  # fmt: skip


def test_an_empty_test_split_gives_an_empty_ready_document():
    doc = compute_drift(np.linspace(0, 1, 50), np.array([]), np.array([], dtype="int64"),
                        np.array([], dtype="int64"), 0.5, detector="d")  # fmt: skip
    assert doc["windows"] == [] and doc["summary"]["n_scored"] == 0
    validate_document("drift.json", doc)


# --------------------------------------------------------------- reading the parquet files
def write_inputs(settings, ref, test, ts_test, labels, detector="xgb_graph"):
    n_ref, n_test = len(ref), len(test)
    ids = np.arange(n_ref + n_test)
    settings.processed_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {"event_id": ids, "split": ["val"] * n_ref + ["test"] * n_test,
         detector: np.concatenate([ref, test]).astype("float32")}
    ).to_parquet(settings.scores_path, index=False)  # fmt: skip
    ts_val = pd.Timestamp("2022-09-01") + pd.to_timedelta(np.arange(n_ref), unit="s")
    ts_all = np.concatenate([ts_val.to_numpy("datetime64[ns]"), ts_test.astype("datetime64[ns]")])
    pd.DataFrame(
        {"event_id": ids, "ts": ts_all,
         "is_illicit": np.concatenate([np.zeros(n_ref, "int8"), labels.astype("int8")])}
    ).to_parquet(settings.events_path, index=False)  # fmt: skip


def test_build_from_parquet_files_matches_the_array_path(tmp_path):
    rng = np.random.default_rng(4)
    settings = Settings(data_dir=tmp_path, drift_windows=4, drift_min_events=100)
    ref = rng.beta(1, 30, 4000)
    s, t, y = make_windows(rng, [(1, 30)] * 2 + [(3, 20)] * 2, 600)
    y = (rng.random(len(s)) < 0.05).astype("int64")
    write_inputs(settings, ref, s, t, y)
    doc = build_drift_document(settings, "xgb_graph", 0.05)
    assert doc["status"] == "ready" and doc["detector"] == "xgb_graph"
    assert [w["level"] for w in doc["windows"]] == ["ok", "ok", "alert", "alert"]
    assert doc["reference"] == {"split": "val", "n_events": 4000}
    assert doc["psi_warn_level"] == 0.1 and doc["psi_alert_level"] == 0.25
    validate_document("drift.json", doc)
    assert build_drift_document(settings, "xgb_graph", 0.05) == doc  # deterministic


def test_missing_inputs_give_none_so_the_placeholder_stays(tmp_path):
    settings = Settings(data_dir=tmp_path)
    assert build_drift_document(settings, "xgb_graph", 0.05) is None


def test_a_scored_event_missing_from_events_is_an_error(tmp_path):
    rng = np.random.default_rng(1)
    settings = Settings(data_dir=tmp_path, drift_windows=2, drift_min_events=10)
    ref = rng.beta(1, 30, 200)
    s, t, y = make_windows(rng, [(1, 30)] * 2, 100)
    write_inputs(settings, ref, s, t, np.zeros(len(s), int))
    events = pd.read_parquet(settings.events_path)
    events.iloc[:-5].to_parquet(settings.events_path, index=False)
    with pytest.raises(SnapshotError, match="missing from events"):
        build_drift_document(settings, "xgb_graph", 0.05)
