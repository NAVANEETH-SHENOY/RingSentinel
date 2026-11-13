"""Guards ring extraction from flagged transfers and the Jaccard ring match."""

import numpy as np
import pytest
from ringsentinel.evaluate.ringmatch import jaccard, match_rings, ring_metrics
from ringsentinel.rings.extract import extract_rings


def _edges(pairs):
    src = np.array([p[0] for p in pairs])
    dst = np.array([p[1] for p in pairs])
    return src, dst


def _extract(pairs, flagged=None, min_size=3, cap=200):
    src, dst = _edges(pairs)
    n = len(pairs)
    score = np.linspace(0.9, 0.5, n)
    amount = np.full(n, 10.0)
    flagged = np.ones(n, dtype=bool) if flagged is None else np.asarray(flagged)
    return extract_rings(src, dst, score, amount, flagged, min_size=min_size, cap=cap)


def test_two_triangles_a_lone_edge_and_a_self_transfer():
    pairs = [(0, 1), (1, 2), (2, 0), (10, 11), (11, 12), (12, 10), (20, 21), (30, 30)]
    rings = _extract(pairs)
    assert [list(r.members) for r in sorted(rings, key=lambda r: r.members[0])] == [
        [0, 1, 2],
        [10, 11, 12],
    ]
    assert all(len(r.rows) == 3 for r in rings)  # the lone edge and the self-transfer are out


def test_unflagged_transfers_do_not_join_rings():
    pairs = [(0, 1), (1, 2), (2, 3)]
    rings = _extract(pairs, flagged=[True, True, False], min_size=3)
    assert len(rings) == 1 and list(rings[0].members) == [0, 1, 2]


def test_ring_score_and_amount_are_means_and_sums_of_its_transfers():
    src, dst = _edges([(0, 1), (1, 2)])
    rings = extract_rings(
        src, dst, np.array([0.8, 0.4]), np.array([100.0, 50.0]), np.ones(2, bool),
        min_size=3, cap=10,
    )  # fmt: skip
    assert rings[0].score == pytest.approx(0.6)
    assert rings[0].amount_inr == pytest.approx(150.0)


def test_no_flags_gives_no_rings():
    assert _extract([(0, 1), (1, 2)], flagged=[False, False]) == []


def test_oversized_component_is_split_and_the_bridge_is_dropped():
    def clique(base):
        nodes = range(base, base + 6)
        return [(a, b) for a in nodes for b in nodes if a < b]

    pairs = clique(0) + clique(100) + [(5, 100)]
    rings = _extract(pairs, cap=6)
    assert sorted(len(r.members) for r in rings) == [6, 6]
    assert all(not r.oversized for r in rings)
    assert sum(len(r.rows) for r in rings) == 30  # the bridging transfer belongs to no ring


def test_extraction_is_deterministic():
    pairs = [(i, (i * 7 + 3) % 40) for i in range(60)]
    a = _extract(pairs, cap=8)
    b = _extract(pairs, cap=8)
    assert [list(r.members) for r in a] == [list(r.members) for r in b]


def test_jaccard_hand_case():
    assert jaccard(np.array([1, 2, 3]), np.array([2, 3, 4])) == pytest.approx(0.5)
    assert jaccard(np.array([], dtype=int), np.array([], dtype=int)) == 0.0


def test_match_boundary_is_inclusive():
    predicted = [np.array([1, 2, 3, 4])]
    truth = {7: np.array([1, 2])}  # J = 2 / 4 = 0.5
    assert len(match_rings(predicted, truth, 0.5)) == 1
    assert len(match_rings(predicted, truth, 0.51)) == 0


def test_matching_is_one_to_one_and_prefers_the_best_overlap():
    truth = {1: np.array([1, 2, 3, 4])}
    predicted = [np.array([1, 2, 3, 4, 5]), np.array([1, 2, 3])]  # J 0.8 and 0.75
    matches = match_rings(predicted, truth, 0.5)
    assert matches == [(0, 1, pytest.approx(0.8))]


def test_ring_metrics_counts_and_empty_prediction():
    truth = {1: np.array([1, 2, 3]), 2: np.array([10, 11, 12])}
    predicted = [np.array([1, 2, 3]), np.array([50, 51, 52])]
    out = ring_metrics(predicted, truth, (0.5,))
    cell = out["by_tau"]["0.5"]
    assert cell["matched"] == 1
    assert cell["precision"] == pytest.approx(0.5)
    assert cell["recall"] == pytest.approx(0.5)
    assert cell["f1"] == pytest.approx(0.5)
    empty = ring_metrics([], truth, (0.5,))["by_tau"]["0.5"]
    assert empty["precision"] == 0.0 and empty["recall"] == 0.0
