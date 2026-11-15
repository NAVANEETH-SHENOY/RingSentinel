"""Stage 08: time-step split and graph features (no leakage across windows, hub control)."""

import numpy as np
import pandas as pd
import pytest
from ringsentinel.elliptic import graph as eg
from ringsentinel.elliptic.load import load_elliptic
from ringsentinel.elliptic.split import assign, split_codes, split_nodes, step_to_ts
from s08_world import make_settings


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("g")
    settings, _ = make_settings(tmp, per_step=40, cross_step_edges=6)
    data = load_elliptic(settings)
    return settings, data


def test_split_boundaries_are_whole_steps():
    steps = np.arange(1, 50)
    parts = assign(steps, 29, 34)
    assert list(parts.codes[[0, 28, 29, 33, 34, 48]]) == [0, 0, 1, 1, 2, 2]
    assert set(parts.categories) == {"train", "val", "test"}


def test_split_nodes_has_no_overlap(built):
    settings, data = built
    codes = split_codes(split_nodes(data.step, settings))
    for lower, upper in ((0, 1), (1, 2)):
        assert data.step[codes == lower].max() < data.step[codes == upper].min()


def test_pseudo_clock_is_strictly_increasing():
    ts = step_to_ts(np.arange(1, 50))
    assert ts.is_monotonic_increasing and ts.is_unique


def test_edge_split_is_the_later_of_its_two_steps(built):
    settings, data = built
    table = eg.edge_table(data, settings)
    later = np.maximum(data.step[data.edge_src], data.step[data.edge_dst])
    expected = np.where(later <= 29, "train", np.where(later <= 34, "val", "test"))
    assert (table["split"].to_numpy() == expected).all()
    assert (table["amount_inr"] == 1.0).all()


def test_graph_columns_are_structure_only():
    assert not set(eg.GRAPH_COLUMNS) & set(eg.EXCLUDED_COLUMNS)
    for col in eg.GRAPH_COLUMNS:
        assert not any(word in col for word in ("amt", "amount", "burst", "hour", "span"))


def test_windows_only_see_past_edges(built):
    """A transaction touched only by a test-step edge has no features in the val window."""
    settings, data = built
    frames = eg.window_frames(data, settings, settings.hub_cap)
    table = eg.edge_table(data, settings)
    test_only_ids = set(table.loc[table["split"] == "test", ["src_account", "dst_account"]]
                        .to_numpy().ravel())  # fmt: skip
    earlier_ids = set(table.loc[table["split"] != "test", ["src_account", "dst_account"]]
                      .to_numpy().ravel())  # fmt: skip
    only_test = test_only_ids - earlier_ids
    assert only_test, "fixture should contain nodes seen only by test-step edges"
    assert not only_test & set(frames["val"].index)
    assert not only_test & set(frames["train"].index)
    assert only_test <= set(frames["test"].index)
    # cross-step edges reach the later window only
    assert len(frames["train"]) < len(frames["val"]) < len(frames["test"])


def test_frames_have_exactly_the_allowed_columns(built):
    settings, data = built
    frames = eg.window_frames(data, settings, settings.hub_cap)
    for frame in frames.values():
        assert list(frame.columns) == list(eg.GRAPH_COLUMNS)
        assert frame.index.is_unique


def test_graph_matrix_gives_nan_for_untouched_nodes(built):
    settings, data = built
    frames = eg.window_frames(data, settings, settings.hub_cap)
    rows = np.arange(data.n)
    matrix = eg.graph_matrix(data, rows, frames["test"])
    touched = np.isin(data.tx_id, frames["test"].index.to_numpy())
    assert np.isnan(matrix[~touched]).all()
    assert not np.isnan(matrix[touched][:, eg.GRAPH_COLUMNS.index("degree")]).any()


def test_hub_cap_marks_the_hub_and_removes_its_graph_features(built):
    settings, data = built
    capped = eg.window_frames(data, settings, 20)["test"]
    uncapped = eg.window_frames(data, settings, eg.NO_HUB_CAP)["test"]
    assert capped["is_hub"].sum() > 0 and uncapped["is_hub"].sum() == 0
    hubs = capped.index[capped["is_hub"] == 1]
    assert capped.loc[hubs, "pagerank"].isna().all()
    assert uncapped.loc[hubs, "pagerank"].notna().all()


def test_frames_are_deterministic(built):
    settings, data = built
    a = eg.window_frames(data, settings, settings.hub_cap)["val"]
    b = eg.window_frames(data, settings, settings.hub_cap)["val"]
    pd.testing.assert_frame_equal(a, b)
