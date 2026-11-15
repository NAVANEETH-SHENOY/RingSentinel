"""Stage 08: the optional GraphSAGE detector. Runs only when PyTorch is installed."""

import json

import numpy as np
import pytest
from ringsentinel.elliptic import gnn
from ringsentinel.elliptic.load import load_elliptic
from ringsentinel.elliptic.pipeline import Context, run_elliptic
from s08_world import make_settings


def test_missing_torch_gives_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.setattr(gnn, "torch_available", lambda: False)
    settings, _ = make_settings(tmp_path, per_step=10)
    ctx = Context(load_elliptic(settings), settings)
    with pytest.raises(gnn.GnnUnavailableError, match="requirements-gnn"):
        gnn.build_graphsage(ctx)


def test_the_rest_of_the_pipeline_runs_without_torch(monkeypatch, tmp_path):
    monkeypatch.setattr(gnn, "torch_available", lambda: False)
    settings, _ = make_settings(tmp_path, per_step=20)
    metrics = run_elliptic(settings, with_ablation=False, write=False)
    assert "graphsage" not in metrics["detectors"]


requires_torch = pytest.mark.skipif(
    not gnn.torch_available(), reason="PyTorch is not installed (optional, requirements-gnn.txt)"
)


@requires_torch
def test_mean_adjacency_rows_sum_to_one_or_zero():
    adj = gnn.mean_adjacency(5, np.array([0, 0, 1, 3]), np.array([1, 2, 2, 3]))
    dense = adj.to_dense().numpy()
    assert dense.shape == (5, 5)
    assert dense[4].sum() == 0  # node 4 has no neighbour
    assert dense[3].sum() == 0  # a self edge is not a neighbour
    for row in (0, 1, 2):
        assert dense[row].sum() == pytest.approx(1.0)
    assert dense[0, 1] == dense[0, 2] == pytest.approx(0.5)


@requires_torch
def test_mean_adjacency_ignores_duplicate_edges():
    import torch

    once = gnn.mean_adjacency(3, np.array([0]), np.array([1])).to_dense()
    twice = gnn.mean_adjacency(3, np.array([0, 0, 1]), np.array([1, 1, 0])).to_dense()
    assert torch.equal(once, twice)


@requires_torch
def test_graphsage_joins_the_same_protocol(tmp_path):
    settings, _ = make_settings(tmp_path, per_step=60)
    metrics = run_elliptic(settings, with_ablation=False, write=False,
                           extra={"graphsage": gnn.build_graphsage})  # fmt: skip
    report = metrics["detectors"]["graphsage"]
    assert "graphsage" in metrics["test_released_for"]
    assert 0.0 <= report["test"]["pr_auc"] <= 1.0
    assert report["threshold"]["chosen_on"] == "validation"


@requires_torch
def test_graphsage_is_deterministic(tmp_path):
    settings, _ = make_settings(tmp_path, per_step=40)
    runs = [
        run_elliptic(settings, with_ablation=False, write=False,
                     extra={"graphsage": gnn.build_graphsage})["detectors"]["graphsage"]
        for _ in range(2)
    ]  # fmt: skip
    assert json.dumps(runs[0], sort_keys=True) == json.dumps(runs[1], sort_keys=True)


@requires_torch
def test_graphsage_never_sees_test_labels(tmp_path):
    import dataclasses

    settings, _ = make_settings(tmp_path, per_step=40)
    data = load_elliptic(settings)
    ctx = Context(data, settings)
    poisoned = dataclasses.replace(data, x=data.x.copy(), y=data.y.copy())
    test_nodes = np.flatnonzero(ctx.codes == 2)
    poisoned.x[test_nodes] = np.nan
    poisoned.y[test_nodes] = 1 - np.clip(poisoned.y[test_nodes], 0, 1)
    val_rows = ctx.rows("val", labelled_only=False)
    clean = gnn.build_graphsage(ctx)(val_rows, "val")
    dirty = gnn.build_graphsage(Context(poisoned, settings))(val_rows, "val")
    np.testing.assert_array_equal(clean, dirty)
