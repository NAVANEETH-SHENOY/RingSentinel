"""Baselines and the Stage 01 runner, on synthetic data in the real file layout."""

import json

import numpy as np
import pandas as pd
from ringsentinel.config import Settings
from ringsentinel.models.baselines import (
    TABULAR_FEATURES,
    VELOCITY_WINDOW_SECONDS,
    tabular_features,
    trailing_counts,
    velocity_scores,
)
from ringsentinel.stage01 import (
    format_baseline_table,
    prepare_baseline_frames,
    run_baselines,
    run_ingest,
    run_split,
    run_verify,
    run_write_manifest,
)


def test_trailing_counts_hand_case():
    group = np.array([0, 0, 0, 1, 0])
    t = np.array([0, 10, 100_000, 5, 10])  # group 0 has events at 0, 10, 10, 100000
    got = trailing_counts(group, t, 86_400)
    # (t-86400, t]: ev@0 -> 1; ev@10 -> 0,10,10 = 3 (ties count each other); ev@100000 -> 1;
    # the only group-1 event -> 1
    assert got.tolist() == [1, 3, 1, 1, 3]


def test_trailing_counts_matches_brute_force():
    rng = np.random.default_rng(1)
    group = rng.integers(0, 20, 400)
    t = rng.integers(0, 400_000, 400)
    window = 50_000
    expected = [
        int(((group == g) & (t > ti - window) & (t <= ti)).sum())
        for g, ti in zip(group, t, strict=True)
    ]
    assert trailing_counts(group, t, window).tolist() == expected


def test_trailing_counts_never_looks_forward():
    group = np.zeros(3, dtype=int)
    t = np.array([0, 100, 200])
    assert trailing_counts(group, t, 1000).tolist() == [1, 2, 3]


def _processed(synthetic):
    settings = Settings(data_dir=synthetic["data_dir"])
    run_ingest(settings)
    meta = run_split(settings)
    return settings, meta


def test_tabular_features_have_expected_columns_and_no_labels(synthetic):
    settings, _ = _processed(synthetic)
    events = pd.read_parquet(settings.events_path)
    feats = tabular_features(events)
    assert list(feats.columns) == TABULAR_FEATURES
    assert not any("illicit" in c or "ring" in c for c in feats.columns)
    assert feats.notna().all().all()


def test_velocity_scores_are_positive_and_use_only_the_past(synthetic):
    settings, _ = _processed(synthetic)
    events = pd.read_parquet(settings.events_path)
    full = velocity_scores(events)
    assert (full >= 1).all()
    half = events.iloc[: len(events) // 2].reset_index(drop=True)
    assert np.array_equal(velocity_scores(half), full[: len(half)])  # later rows change nothing
    assert VELOCITY_WINDOW_SECONDS == 86_400


def test_split_step_reports_rows_and_rings(synthetic):
    _, meta = _processed(synthetic)
    assert sum(meta["rows"].values()) == synthetic["n_rows"]
    assert all(meta["illicit_rows"][n] > 0 for n in ("train", "val", "test"))
    assert sum(meta["rings_by_split"].values()) == synthetic["n_blocks"]


def test_baseline_frames_never_contain_test_rows(synthetic):
    settings, _ = _processed(synthetic)
    events = pd.read_parquet(settings.events_path)
    split_table = pd.read_parquet(settings.split_path)
    train, val = prepare_baseline_frames(events, split_table)
    test_ids = set(split_table.loc[split_table["split"] == "test", "event_id"])
    assert test_ids and not (test_ids & set(train["event_id"])) and not (
        test_ids & set(val["event_id"])
    )
    assert train["ts"].max() < val["ts"].min()


def test_run_baselines_end_to_end_and_deterministic(synthetic):
    settings, _ = _processed(synthetic)
    first = run_baselines(settings)
    second = run_baselines(settings)
    assert first["tabular_xgboost"] == second["tabular_xgboost"]  # fixed seed, same output
    assert first["velocity_rule"] == second["velocity_rule"]
    for name in ("velocity_rule", "tabular_xgboost"):
        m = first[name]
        assert 0 < m["pr_auc"] <= 1 and m["positives"] > 0 and m["prevalence"] > 0
    assert "test" not in json.dumps(first["split_rows"])
    saved = json.loads(settings.baseline_metrics_path.read_text())
    assert saved["seed"] == settings.seed
    assert "VALIDATION" in format_baseline_table(first)


def test_manifest_step_and_verify(synthetic):
    settings = Settings(data_dir=synthetic["data_dir"])
    assert "No manifest entry" in run_verify(settings)[0]
    run_write_manifest(settings)
    assert run_verify(settings) == []
    synthetic["patterns_path"].write_text("tampered\n")
    assert run_verify(settings)
