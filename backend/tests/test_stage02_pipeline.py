"""Stage 02 end to end on the synthetic dataset (after the Stage 01 steps)."""

import json

import pandas as pd
from ringsentinel.config import Settings
from ringsentinel.graph.hubs import HUB_CAP_GRID
from ringsentinel.stage01 import run_ingest, run_split
from ringsentinel.stage02 import (
    WINDOWS,
    format_ablation,
    load_events,
    ring_accounts,
    run_ablation,
    run_features,
    run_noise,
    run_tune,
)


def _ready(synthetic):
    settings = Settings(data_dir=synthetic["data_dir"], community_cap=30)
    run_ingest(settings)
    run_split(settings)
    return settings


def test_full_stage02_run_writes_every_output(synthetic):
    settings = _ready(synthetic)
    noise_report = run_noise(settings)
    tuned = run_tune(settings)
    out = run_features(settings)
    ablation = run_ablation(settings)

    assert tuned["chosen_cap"] in HUB_CAP_GRID and json.loads(
        settings.hub_cap_tuning_path.read_text(encoding="utf-8")
    )["chosen_cap"] == tuned["chosen_cap"]
    assert out["hub_cap"] == tuned["chosen_cap"]  # the tuned value is picked up automatically
    for path in (
        settings.noise_path, settings.noise_report_path, settings.features_path,
        settings.pruning_report_path, settings.community_report_path, settings.ablation_path,
    ):  # fmt: skip
        assert path.exists()
    assert noise_report["accounts"] == pd.read_parquet(settings.noise_path).shape[0]
    assert len(ablation["rows"]) == 4 * len(WINDOWS)
    assert "transfer_controlled" in format_ablation(ablation)


def test_feature_table_shape_windows_and_nulls(synthetic):
    settings = _ready(synthetic)
    run_noise(settings)
    run_tune(settings)
    run_features(settings)
    features = pd.read_parquet(settings.features_path)
    events = load_events(settings)

    assert set(features["window"].astype(str)) == set(WINDOWS)
    for window in WINDOWS:  # rows are the accounts active in that window's own split
        own = events[events["split"] == window]
        active = set(own["src_account"].astype(str)) | set(own["dst_account"].astype(str))
        got = features[features["window"] == window]
        assert set(got["account"]) == active and got["account"].is_unique
    assert not any(c in features.columns for c in ("is_illicit", "ring_id", "ring_split"))
    flow_cols = ["out_cnt", "in_cnt", "degree", "burst_share", "is_hub", "community_id"]
    assert features[flow_cols].notna().all().all()
    graph_cols = ["triangles", "cycles3", "pagerank", "comm_size"]
    hub_rows = features["is_hub"] == 1
    assert features.loc[~hub_rows, graph_cols].notna().all().all()
    assert features.loc[hub_rows, graph_cols].isna().all().all()
    assert (features.loc[hub_rows, "community_id"] == -1).all()


def test_features_are_reproducible(synthetic):
    settings = _ready(synthetic)
    run_noise(settings)
    run_tune(settings)
    run_features(settings)
    first = pd.read_parquet(settings.features_path)
    run_features(settings)
    pd.testing.assert_frame_equal(first, pd.read_parquet(settings.features_path))


def test_test_window_labels_are_not_read_for_reporting(synthetic):
    settings = _ready(synthetic)
    run_noise(settings)
    run_tune(settings)
    run_features(settings)
    pruning = json.loads(settings.pruning_report_path.read_text(encoding="utf-8"))["windows"]
    communities = json.loads(settings.community_report_path.read_text(encoding="utf-8"))
    assert "ring_accounts_in_window" in pruning["train"]
    assert "ring_accounts_in_window" in pruning["val"]
    assert "ring_accounts_in_window" not in pruning["test"]
    assert "ring_recovery_diagnostic" not in communities["test"]
    assert "ring_recovery_diagnostic" in communities["val"]


def test_ring_accounts_helper(synthetic):
    settings = _ready(synthetic)
    rings = ring_accounts(load_events(settings))
    assert len(rings) == synthetic["n_blocks"] and all(len(v) >= 7 for v in rings.values())
