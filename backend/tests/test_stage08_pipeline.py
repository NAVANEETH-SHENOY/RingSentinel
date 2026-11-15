"""Stage 08: the Elliptic protocol end to end on synthetic files (not real results)."""

import dataclasses
import json

import numpy as np
import pandas as pd
import pytest
from ringsentinel.detect.guard import SplitVault, TestSplitAccessError
from ringsentinel.elliptic.load import load_elliptic
from ringsentinel.elliptic.pipeline import (
    ABLATIONS,
    DETECTORS,
    Context,
    cross_dataset_table,
    evaluate_detector,
    fit_detector,
    format_results,
    run_elliptic,
)  # fmt: skip
from ringsentinel.evaluate.metrics import best_f1_threshold
from s08_world import make_settings
from sklearn.metrics import average_precision_score


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("p")
    settings, _ = make_settings(tmp, per_step=120)
    metrics = run_elliptic(settings)
    return settings, metrics, pd.read_parquet(settings.scores_path)


def test_every_detector_and_ablation_is_reported(run):
    _, metrics, _ = run
    assert set(metrics["detectors"]) == set(DETECTORS) | set(ABLATIONS)
    assert metrics["detectors"]["graph_xgb_nohub"]["role"] == "ablation"


def test_test_split_is_released_once_per_detector(run):
    _, metrics, _ = run
    assert metrics["test_released_for"] == sorted(set(DETECTORS) | set(ABLATIONS))


def test_vault_refuses_a_second_release(tmp_path):
    settings, _ = make_settings(tmp_path, per_step=15)
    ctx = Context(load_elliptic(settings), settings)
    vault = SplitVault({"train": ctx.rows("train", True), "val": ctx.rows("val", True)},
                       lambda: ctx.rows("test", False))  # fmt: skip
    predict = fit_detector("degree_rule", ctx)
    evaluate_detector(ctx, vault, "degree_rule", predict)
    with pytest.raises(TestSplitAccessError):
        evaluate_detector(ctx, vault, "degree_rule", predict)


def test_destroying_the_test_period_does_not_change_anything_fitted(tmp_path):
    """Poison every test-step feature and label: train and validation scores must not move."""
    settings, _ = make_settings(tmp_path, per_step=60, cross_step_edges=4)
    data = load_elliptic(settings)
    ctx = Context(data, settings)
    poisoned = dataclasses.replace(data, x=data.x.copy(), y=data.y.copy())
    test_nodes = np.flatnonzero(ctx.codes == 2)
    poisoned.x[test_nodes] = np.nan
    poisoned.y[test_nodes] = 1 - np.clip(poisoned.y[test_nodes], 0, 1)
    ctx_poisoned = Context(poisoned, settings)
    val_rows = ctx.rows("val", labelled_only=False)
    for name in (*DETECTORS, *ABLATIONS):
        clean = fit_detector(name, ctx)(val_rows, "val")
        dirty = fit_detector(name, ctx_poisoned)(val_rows, "val")
        np.testing.assert_array_equal(clean, dirty, err_msg=name)


def test_threshold_is_the_validation_f1_optimum(run):
    settings, metrics, scores = run
    val = scores[(scores["split"] == "val") & (scores["label"] >= 0)]
    choice = best_f1_threshold(val["label"].to_numpy(), val["graph_xgb"].to_numpy("float64"))
    reported = metrics["detectors"]["graph_xgb"]["threshold"]["f1"]
    assert reported == pytest.approx(choice["threshold"])
    assert metrics["detectors"]["graph_xgb"]["threshold"]["chosen_on"] == "validation"


def test_pr_auc_matches_scikit_learn(run):
    _, metrics, scores = run
    test = scores[(scores["split"] == "test") & (scores["label"] >= 0)]
    for name in ("graph_xgb", "local_xgb", "degree_rule"):
        expected = average_precision_score(test["label"], test[name].astype("float64"))
        assert metrics["detectors"][name]["test"]["pr_auc"] == pytest.approx(expected, abs=1e-9)


def test_only_labelled_rows_are_judged_but_all_rows_are_scored(run):
    _, metrics, scores = run
    test = scores[scores["split"] == "test"]
    assert test["graph_xgb"].notna().all()
    assert scores.loc[scores["split"] == "train", "graph_xgb"].isna().all()
    judged = metrics["detectors"]["graph_xgb"]["test"]["labelled"]
    assert judged == int((test["label"] >= 0).sum()) < len(test)


def test_graph_features_help_on_this_synthetic_world(run):
    """Sanity of the wiring only: the synthetic cluster structure is built to reward it."""
    _, metrics, _ = run
    assert metrics["detectors"]["graph_xgb"]["test"]["pr_auc"] >= 0.5
    assert (metrics["detectors"]["degree_rule"]["test"]["pr_auc"]
            < metrics["detectors"]["graph_xgb"]["test"]["pr_auc"])  # fmt: skip


def test_runs_are_deterministic(tmp_path):
    settings, _ = make_settings(tmp_path, per_step=40)
    first = run_elliptic(settings, with_ablation=False, write=False)
    second = run_elliptic(settings, with_ablation=False, write=False)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_psi_alerts_on_shifted_steps_and_is_quiet_without_a_shift(tmp_path):
    shifted, _ = make_settings(tmp_path / "a", per_step=120, shift_after=43)
    quiet, _ = make_settings(tmp_path / "b", per_step=120, shift_after=99)
    a = run_elliptic(shifted, with_ablation=False, write=False)["detectors"]["graph_xgb"]
    b = run_elliptic(quiet, with_ablation=False, write=False)["detectors"]["graph_xgb"]
    before = [r for r in a["per_step"] if r["step"] <= 43]
    after = [r for r in a["per_step"] if r["step"] > 43]
    assert all(r["psi_status"] != "alert" for r in before)
    assert all(r["psi_status"] == "alert" for r in after)
    assert all(r["psi_status"] != "alert" for r in b["per_step"])


def test_small_steps_report_insufficient_psi(tmp_path):
    settings, _ = make_settings(tmp_path, per_step=20)  # 20 nodes per step < 50 minimum
    steps = run_elliptic(settings, with_ablation=False, write=False)["detectors"]["graph_xgb"]
    assert {r["psi_status"] for r in steps["per_step"]} == {"insufficient"}


def test_outputs_are_written(run):
    settings, metrics, scores = run
    assert json.loads(settings.metrics_path.read_text("utf-8"))["meta"]["seed"] == 42
    assert "graph_xgb" in settings.results_path.read_text("utf-8")
    assert len(scores) == metrics["meta"]["graph"]["nodes"]
    assert set(scores["split"]) == {"train", "val", "test"}


def test_meta_states_what_does_not_apply(run):
    _, metrics, _ = run
    text = " ".join(metrics["meta"]["not_applicable"])
    assert "ring" in text and "rupee" in text and "velocity" in text
    assert "amount" not in " ".join(metrics["meta"]["graph_columns"])


def test_format_results_lists_every_detector(run):
    _, metrics, _ = run
    text = format_results(metrics)
    for name in metrics["detectors"]:
        assert f"| {name} |" in text
    assert "Per test time step" in text


def test_cross_dataset_table_with_and_without_ibm(run):
    _, ell, _ = run
    none = cross_dataset_table(None, ell)
    assert "not run" in none and "n/a" in none
    ibm = {"detectors": {k: {"test": {"pr_auc": 0.5, "at_f1_threshold": {"f1": 0.25}}}
                         for k in ("velocity", "iforest", "xgb_tabular", "xgb_graph")}}  # fmt: skip
    both = cross_dataset_table(ibm, ell)
    assert "0.500" in both and "0.250" in both
    assert both.count("not run") == 0
    assert np.isfinite(ell["detectors"]["graph_xgb"]["test"]["pr_auc"])
