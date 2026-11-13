import numpy as np
import pandas as pd
import pytest
from ringsentinel.features.build import build_window_features
from ringsentinel.features.node import hourly_groups, pagerank
from ringsentinel.graph.build import cumulative_events
from toy_events import hub_world, make_events

ARGS = {"hub_cap": 10, "community_cap": 200, "resolution": 1.0, "seed": 42}
COLS = ["src_account", "dst_account", "ts", "amount_inr"]


def _features(events, **kw):
    frame, graph, community, oversized = build_window_features(events[COLS], **{**ARGS, **kw})
    return frame.set_index("account"), graph, community, oversized


def test_hand_checked_node_and_community_values():
    f, _, community, _ = _features(hub_world())
    a1 = f.loc["a1"]
    assert (a1["out_deg"], a1["in_deg"], a1["degree"]) == (1, 2, 3)  # a1>a2; a3>a1 and H>a1
    assert a1["triangles"] == 1 and a1["cycles3"] == 1  # the directed 3-cycle
    assert f.loc["a2", "cycles3"] == 1 and f.loc["a2", "triangles"] == 1
    assert f.loc["p1", "recip_partners"] == 1 and f.loc["p1", "self_cnt"] == 1
    assert f.loc["p1", "out_amt"] == 50.0 and f.loc["p1", "in_amt"] == 25.0
    cyc = f.loc["a1", "community_id"]
    assert f.loc["a1", "comm_size"] == 3 and f.loc["a3", "community_id"] == cyc
    assert f.loc["a1", "comm_cycles3"] == 1.0 and f.loc["a1", "comm_density"] == 1.0


def test_hub_rows_have_no_graph_features_and_no_community():
    f, graph, community, _ = _features(hub_world())
    hub = f.loc["H"]
    assert hub["is_hub"] == 1 and hub["community_id"] == -1
    for col in ("triangles", "cycles3", "pagerank", "comm_size", "kept_degree"):
        assert np.isnan(hub[col])
    assert hub["degree"] == 26  # raw degree is still reported
    assert f.loc["a1", "hub_neighbor_share"] == pytest.approx(1 / 3)  # a1 touches the hub


def test_burst_share_by_hand():
    events = make_events(
        [("x", "y", 1, 30.0), ("x", "y", 10, 30.0), ("x", "y", 130, 40.0)]
    )  # two transfers in hour 0 (60), one in hour 2 (40)
    f, *_ = _features(events)
    assert f.loc["x", "burst_share"] == pytest.approx(0.6)
    assert f.loc["x", "active_hours"] == 2 and f.loc["x", "span_hours"] == 2
    assert f.loc["x", "txn_per_active_hour"] == pytest.approx(1.5)


def test_hourly_groups_hand_case():
    out = hourly_groups(
        np.array([0, 0, 1]), np.array([5, 5, 9]), np.array([2.0, 3.0, 7.0]), 3
    )
    assert out["max_hour_amount"].tolist() == [5.0, 7.0, 0.0]
    assert out["active_hours"].tolist() == [1, 1, 0]


def test_pagerank_mean_is_one_and_hand_case():
    rank = pagerank(3, np.array([0, 1]), np.array([1, 2]), np.array([1.0, 1.0]))
    assert rank.mean() == pytest.approx(1.0)
    assert rank[2] > rank[1] > rank[0]  # a chain 0>1>2 pushes rank downstream


def test_deterministic():
    one, *_ = _features(hub_world())
    two, *_ = _features(hub_world())
    pd.testing.assert_frame_equal(one, two)


def test_label_columns_cannot_change_features():
    base = hub_world()
    plain, *_ = _features(base)
    with_labels = base.assign(ring_id=3, is_illicit=1, split="val")
    labelled, *_ = _features(with_labels)
    pd.testing.assert_frame_equal(plain, labelled)
    flipped, *_ = _features(base.assign(ring_id=1, is_illicit=0))
    pd.testing.assert_frame_equal(plain, flipped)


def test_missing_columns_are_rejected():
    with pytest.raises(ValueError, match="missing required columns"):
        build_window_features(hub_world()[["src_account"]], **ARGS)


def test_validation_features_ignore_everything_after_the_boundary():
    rng = np.random.default_rng(3)
    names = [f"n{i:02d}" for i in range(40)]
    rows = []
    for minute in range(0, 3000, 5):
        a, b = rng.choice(names, 2, replace=False)
        split = "train" if minute < 1000 else "val" if minute < 2000 else "test"
        rows.append((a, b, minute, float(rng.integers(1, 500)), split))
    events = make_events(rows)

    def val_features(frame):
        window = cumulative_events(frame, "val")
        out, *_ = _features(window)
        return out

    before = val_features(events)
    changed = events.copy()
    test_rows = changed["split"] == "test"
    changed.loc[test_rows, "amount_inr"] *= 1000
    extra = make_events(
        [("n01", "zz_new", 2500, 5.0, "test"), ("zz_new", "n02", 2600, 5.0, "test")]
    )
    changed = pd.concat([changed, extra], ignore_index=True)
    pd.testing.assert_frame_equal(before, val_features(changed))
    assert "zz_new" not in before.index
