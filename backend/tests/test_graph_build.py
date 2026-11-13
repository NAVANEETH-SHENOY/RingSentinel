import numpy as np
import pandas as pd
import pytest
from ringsentinel.graph.build import build_graph, cumulative_events, pruning_report
from ringsentinel.graph.communities import component_labels
from toy_events import hub_world, make_events


def _id(graph, name):
    return int(graph.accounts.get_loc(name))


def test_degrees_pairs_and_self_transfers():
    g = build_graph(hub_world(), hub_cap=10)
    assert g.n == 3 + 26 + 2  # a1..a3, H and 25 spokes, p1 p2
    assert g.degree[_id(g, "H")] == 26 and g.degree[_id(g, "a1")] == 3
    assert g.self_cnt[_id(g, "p1")] == 1 and g.self_cnt.sum() == 1
    assert len(g.und_a) == 3 + 26 + 1  # triangle, hub star incl. link to a1, the p1-p2 pair
    assert len(g.dir_src) == 3 + 26 + 2  # p1>p2 and p2>p1 are two directed pairs
    p1, p2 = _id(g, "p1"), _id(g, "p2")
    pair = (g.und_a == min(p1, p2)) & (g.und_b == max(p1, p2))
    assert g.und_cnt[pair].tolist() == [2] and g.und_amt[pair].tolist() == [75.0]


def test_weights_follow_the_idf_formula():
    g = build_graph(hub_world(), hub_cap=10)
    i, j = _id(g, "a2"), _id(g, "a3")  # both have degree 2
    edge = (g.und_a == min(i, j)) & (g.und_b == max(i, j))
    assert g.und_weight[edge][0] == pytest.approx(1 / np.log2(3))
    p1, p2 = _id(g, "p1"), _id(g, "p2")  # both degree 1
    edge = (g.und_a == min(p1, p2)) & (g.und_b == max(p1, p2))
    assert g.und_weight[edge][0] == pytest.approx(1.0)
    hub_edge = (g.und_a == _id(g, "H")) | (g.und_b == _id(g, "H"))
    assert g.und_weight[hub_edge].max() == pytest.approx(1 / np.log2(27))  # hub edges are weak


def test_hub_is_down_weighted_and_a_capped_hub_is_dropped():
    loose = build_graph(hub_world(), hub_cap=1000)
    strict = build_graph(hub_world(), hub_cap=10)
    assert not loose.is_hub.any()
    assert strict.is_hub.sum() == 1 and strict.is_hub[_id(strict, "H")]
    assert strict.und_kept.sum() == 4  # triangle + the pair; all 26 hub edges are gone


def test_known_components_with_and_without_hub_control():
    loose = build_graph(hub_world(), hub_cap=1000)
    strict = build_graph(hub_world(), hub_cap=10)
    for graph, expected in ((loose, 29), (strict, 3)):
        kept = graph.und_kept
        _, labels = component_labels(graph.n, graph.und_a[kept], graph.und_b[kept])
        giant = np.bincount(labels).max()
        assert giant == expected
    assert component_labels(4, np.array([], dtype=int), np.array([], dtype=int))[0] == 4


def test_pruning_report_counts():
    g = build_graph(hub_world(), hub_cap=10)
    ring = np.array([_id(g, "H"), _id(g, "a1")])
    report = pruning_report(g, ring)
    assert report["hub_nodes_dropped"] == 1 and report["edges_dropped"] == 26
    assert report["top_dropped_hubs"][0] == {"account": "H", "degree": 26}
    assert report["ring_accounts_dropped_as_hubs"] == 1


def test_cumulative_windows_are_past_only():
    events = make_events(
        [("a", "b", 1, 1.0, "train"), ("b", "c", 2, 1.0, "val"), ("c", "d", 3, 1.0, "test")]
    )
    sizes = {w: len(cumulative_events(events, w)) for w in ("train", "val", "test")}
    assert sizes == {"train": 1, "val": 2, "test": 3}
    with pytest.raises(ValueError, match="Unknown window"):
        cumulative_events(events, "future")


def test_graph_ignores_every_column_but_the_four_it_needs():
    base = hub_world()
    noisy = base.assign(ring_id=7, is_illicit=1)
    a = build_graph(base[["src_account", "dst_account", "ts", "amount_inr"]], 10)
    b = build_graph(noisy[["src_account", "dst_account", "ts", "amount_inr"]], 10)
    assert np.array_equal(a.und_weight, b.und_weight) and a.accounts.equals(b.accounts)
    assert isinstance(a.accounts, pd.Index)
