import numpy as np
from ringsentinel.graph.communities import detect_communities


def _clique(nodes):
    return [(a, b) for i, a in enumerate(nodes) for b in nodes[i + 1 :]]


def _run(n, edges, cap, hubs=()):
    a = np.array([e[0] for e in edges], dtype=int)
    b = np.array([e[1] for e in edges], dtype=int)
    is_hub = np.zeros(n, dtype=bool)
    is_hub[list(hubs)] = True
    return detect_communities(n, a, b, np.ones(len(a)), is_hub, cap, 1.0, 42)


def test_small_components_are_kept_whole():
    comm, over = _run(7, _clique([0, 1, 2]) + _clique([3, 4]), cap=10)
    assert comm[0] == comm[1] == comm[2] and comm[3] == comm[4]
    assert len({comm[0], comm[3], comm[5], comm[6]}) == 4  # 5 and 6 are singletons
    assert not over.any()


def test_two_cliques_joined_by_a_bridge_are_split_by_louvain():
    edges = _clique(list(range(5))) + _clique(list(range(5, 10))) + [(4, 5)]
    comm, over = _run(10, edges, cap=6)
    assert len(set(comm[:5])) == 1 and len(set(comm[5:])) == 1 and comm[0] != comm[9]
    assert not over.any()
    assert sorted(set(comm.tolist())) == [0, 1]  # contiguous ids


def test_unsplittable_oversized_community_is_flagged():
    comm, over = _run(12, _clique(list(range(12))), cap=5)
    assert len(set(comm.tolist())) == 1 and over.tolist() == [True]


def test_hubs_get_minus_one_and_ids_stay_contiguous():
    edges = _clique([0, 1, 2]) + [(3, 4)]
    comm, _ = _run(6, edges, cap=10, hubs=[3])
    assert comm[3] == -1
    assert sorted(set(comm[comm >= 0].tolist())) == list(range(len(set(comm[comm >= 0]))))


def test_deterministic_for_a_fixed_seed():
    edges = _clique(list(range(8))) + _clique(list(range(8, 16))) + [(7, 8)]
    first, _ = _run(16, edges, cap=9)
    second, _ = _run(16, edges, cap=9)
    assert np.array_equal(first, second)
