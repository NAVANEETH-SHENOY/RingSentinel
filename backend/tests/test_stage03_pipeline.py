"""Stage 03 end to end on the synthetic dataset: outputs, protocol and leakage guards."""

import json

import numpy as np
import pandas as pd
import pytest
from ringsentinel import stage02, stage03
from ringsentinel.config import Settings
from ringsentinel.evaluate.metrics import average_precision, best_f1_threshold
from ringsentinel.evaluate.report import ExtractionSettings, Scored, SplitCtx, latency_block
from s03_world import write_world


def _run_all(data_dir, mutate=None):
    settings = Settings(data_dir=data_dir)
    events, split, rings = write_world(settings)
    if mutate is not None:
        events = mutate(events, split)
        events.to_parquet(settings.events_path, index=False)
    stage02.run_features(settings)
    stage03.run_detect(settings)
    metrics = stage03.run_evaluate(settings)
    stage03.run_ablate(settings)
    stage03.run_robustness(settings)
    return settings, metrics


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return _run_all(tmp_path_factory.mktemp("world"))


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_every_output_file_is_written(world):
    settings, _ = world
    for path in (
        settings.scores_path, settings.scores_ablation_path, settings.features_nohub_path,
        settings.detect_report_path, settings.metrics_path, settings.rings_path,
        settings.ablations_path, settings.robustness_path, settings.latency_path,
        settings.results_table_path,
        settings.models_dir / "xgb_tabular.json", settings.models_dir / "xgb_graph.json",
        settings.models_dir / "iforest.joblib",
    ):  # fmt: skip
        assert path.exists(), path.name


def test_scores_cover_validation_and_test_rows_with_no_gaps(world):
    settings, _ = world
    scores = pd.read_parquet(settings.scores_path)
    split = pd.read_parquet(settings.split_path)
    expected = split[split["split"].isin(["val", "test"])]
    assert len(scores) == len(expected)
    assert set(scores["event_id"]) == set(expected["event_id"])
    for name in stage03.DETECTORS:
        assert scores[name].notna().all() and np.isfinite(scores[name]).all()


def test_thresholds_are_chosen_on_validation_labels_only(world):
    settings, metrics = world
    prep = stage03.load_prepared(settings)
    scores = stage03.read_scores(settings.scores_path, prep)
    y_val = prep.y[prep.rows("val")]
    for name in stage03.DETECTORS:
        again = best_f1_threshold(y_val, scores[name][0])["threshold"]
        assert metrics["detectors"][name]["thresholds"]["f1"] == pytest.approx(again)
        assert metrics["detectors"][name]["val"]["pr_auc"] == pytest.approx(
            average_precision(y_val, scores[name][0])
        )
        y_test = prep.y[prep.rows("test")]
        assert metrics["detectors"][name]["test"]["pr_auc"] == pytest.approx(
            average_precision(y_test, scores[name][1])
        )


def test_graph_detector_beats_chance_on_validation_and_velocity_does_not(world):
    _, metrics = world
    detectors = metrics["detectors"]
    prevalence = detectors["xgb_graph"]["val"]["prevalence"]
    assert detectors["xgb_graph"]["val"]["pr_auc"] > 5 * prevalence
    assert detectors["velocity"]["val"]["pr_auc"] < 0.2


def test_default_cost_setting_row_matches_the_operating_point(world):
    _, metrics = world
    for name in stage03.DETECTORS:
        sweep = metrics["detectors"][name]["operating_points"]["net_value"]["test"]
        row = next(
            r for r in metrics["cost_sweep"][name]
            if (r["capture_rate"], r["review_cost_inr"], r["fp_cost_inr"]) == (1.0, 250.0, 500.0)
        )  # fmt: skip
        assert row["test_net_value_inr"] == pytest.approx(sweep["net_value_inr"])


def test_rings_file_has_members_score_and_top_features(world):
    settings, metrics = world
    rings = _load(settings.rings_path)
    assert rings["detector"] == "xgb_graph" and rings["split"] == "test"
    if metrics["detectors"]["xgb_graph"]["thresholds"]["net_value"] in ("inf", "-inf"):
        assert rings["rings"] == [] and "note" in rings
        return
    assert rings["rings"], "expected at least one ring on the synthetic data"
    for ring in rings["rings"]:
        assert ring["members"] and ring["n_members"] >= 3
        assert 0.0 <= ring["score"] <= 1.0
        assert 1 <= len(ring["top_features"]) <= 5


def test_ablation_has_the_three_variants(world):
    settings, _ = world
    variants = _load(settings.ablations_path)["variants"]
    assert set(variants) == set(stage03.ABLATION_DETECTORS)
    assert "hub control OFF" in variants["xgb_graph_nohub"]["label"]


def test_robustness_without_dropout_reproduces_the_main_test_score(world):
    settings, metrics = world
    levels = _load(settings.robustness_path)["levels"]
    assert [lv["dropout"] for lv in levels] == list(stage03.ROBUSTNESS_LEVELS)
    assert levels[0]["test_pr_auc"] == pytest.approx(
        metrics["detectors"]["xgb_graph"]["test"]["pr_auc"], rel=1e-5
    )
    assert levels[-1]["events_kept"] < levels[0]["events_kept"]


def test_results_table_names_every_detector(world):
    settings, _ = world
    table = settings.results_table_path.read_text(encoding="utf-8")
    for name in stage03.DETECTORS:
        assert f"| {name} |" in table
    assert "pattern rings only" in table


def test_metrics_json_has_no_infinity_literals(world):
    settings, _ = world
    text = settings.metrics_path.read_text(encoding="utf-8")
    assert "Infinity" not in text and "NaN" not in text
    json.loads(text)


def test_the_test_split_is_released_once_per_detector(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path)
    write_world(settings)
    stage02.run_features(settings)
    seen = []
    original = stage03.make_vault

    def spy(prep):
        vault = original(prep)
        seen.append(vault)
        return vault

    monkeypatch.setattr(stage03, "make_vault", spy)
    stage03.run_detect(settings)
    assert seen[0].released == set(stage03.DETECTORS)


def test_changing_test_labels_and_test_events_cannot_change_any_fit(tmp_path_factory, world):
    """Leakage guard: rewrite everything about the test split; train/val results must not move."""

    def corrupt(events, split):
        merged = events.merge(split, on="event_id")
        test = (merged["split"] == "test").to_numpy()
        out = events.copy()
        out.loc[test, "is_illicit"] = 1 - out.loc[test, "is_illicit"]
        out.loc[test, "amount_inr"] = out.loc[test, "amount_inr"] * 7.0
        return out

    base_settings, _ = world
    other_settings, _ = _run_all(tmp_path_factory.mktemp("corrupt"), mutate=corrupt)
    prep_a = stage03.load_prepared(base_settings)
    prep_b = stage03.load_prepared(other_settings)
    a = stage03.read_scores(base_settings.scores_path, prep_a)
    b = stage03.read_scores(other_settings.scores_path, prep_b)
    for name in stage03.DETECTORS:
        assert np.array_equal(a[name][0], b[name][0]), f"{name}: validation scores moved"
    for model in ("xgb_tabular.json", "xgb_graph.json"):
        assert (base_settings.models_dir / model).read_bytes() == (
            other_settings.models_dir / model
        ).read_bytes()
    assert not np.array_equal(a["xgb_graph"][1], b["xgb_graph"][1])  # test inputs did change


def test_detect_is_reproducible(tmp_path, world):
    base_settings, _ = world
    settings = Settings(data_dir=tmp_path)
    write_world(settings)
    stage02.run_features(settings)
    stage03.run_detect(settings)
    first = pd.read_parquet(base_settings.scores_path)
    second = pd.read_parquet(settings.scores_path)
    pd.testing.assert_frame_equal(first, second)


def test_evaluation_refuses_scores_from_other_events(tmp_path, world):
    settings, _ = world
    prep = stage03.load_prepared(settings)
    frame = pd.read_parquet(settings.scores_path)
    frame.loc[0, "event_id"] = -5
    bad = tmp_path / "scores.parquet"
    frame.to_parquet(bad, index=False)
    with pytest.raises(ValueError, match="does not match"):
        stage03.read_scores(bad, prep)


def _ctx():
    # ring 1 has transfers at minutes 10, 20, 30; the event clock has an event every 5 minutes
    minutes = np.array([10, 20, 30, 50, 60])
    return SplitCtx(
        name="test", event_id=np.arange(5), minutes=minutes, src=np.arange(5), dst=np.arange(5) + 1,
        amount_inr=np.ones(5), y=np.array([1, 1, 1, 0, 0]),
        ring_id=np.array([1, 1, 1, -1, -1]), n_accounts=7,
        truth={1: np.array([0, 1, 2, 3])},
    )  # fmt: skip


def test_latency_counts_events_between_first_event_and_first_flag():
    ext = ExtractionSettings(min_size=3, cap=50, resolution=1.0, seed=1)
    scored = Scored(_ctx(), np.array([0.1, 0.2, 0.9, 0.1, 0.1]), ext)
    clock = np.arange(0, 100, 5)  # events at 0, 5, ..., 95
    out = latency_block(scored, 0.5, clock)
    assert out["rings_with_a_flagged_transfer"] == 1
    assert out["minutes_median"] == 20  # first event 10, first flagged transfer 30
    assert out["events_median"] == 4  # events at 10, 15, 20, 25 come before minute 30
    missed = latency_block(scored, 0.95, clock)
    assert missed["rings_with_a_flagged_transfer"] == 0 and missed["share_detected"] == 0.0
    assert missed["events_median"] is None


def test_the_leakage_guard_has_power(tmp_path_factory, world):
    """Same corruption applied to the VALIDATION split must move validation results."""

    def corrupt(events, split):
        merged = events.merge(split, on="event_id")
        val = (merged["split"] == "val").to_numpy()
        out = events.copy()
        out.loc[val, "is_illicit"] = 1 - out.loc[val, "is_illicit"]
        return out

    base_settings, _ = world
    other_settings, _ = _run_all(tmp_path_factory.mktemp("val_corrupt"), mutate=corrupt)
    a = stage03.read_scores(base_settings.scores_path, stage03.load_prepared(base_settings))
    b = stage03.read_scores(other_settings.scores_path, stage03.load_prepared(other_settings))
    assert not np.array_equal(a["xgb_graph"][0], b["xgb_graph"][0])


def test_full_results_markdown_and_numeric_differences(world):
    settings, metrics = world
    ablations = _load(settings.ablations_path)
    robustness = _load(settings.robustness_path)
    latency = _load(settings.latency_path)
    text = stage03.format_full_results(metrics, ablations, robustness, latency)
    for heading in ("All detectors on the temporal test split", "Ablation", "Robustness",
                    "Detection latency", "Cost sensitivity"):  # fmt: skip
        assert heading in text
    assert "INR" in text and "placeholder FX" in text
    assert stage03.numeric_differences(metrics, metrics) == []
    changed = json.loads(json.dumps(metrics))
    changed["detectors"]["velocity"]["test"]["pr_auc"] += 0.1
    diffs = stage03.numeric_differences(metrics, changed)
    assert len(diffs) == 1 and "velocity" in diffs[0]
