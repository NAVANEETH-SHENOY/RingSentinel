"""Case facts, aliases, structure detection and the four graph tools."""

import json

import pytest
from ringsentinel.ai.facts import CaseFacts
from ringsentinel.ai.tools import MAX_ROWS, TOOL_NAMES, ToolBox, ToolError
from s06_cases import (
    CHAIN,
    CYCLE,
    T1,
    T2,
    T3,
    T4,
    A,
    B,
    C,
    S,
    fan_out_case,
    make_case,
    make_edge,
)


def test_aliases_follow_volume_and_are_stable():
    f = CaseFacts(fan_out_case())
    assert f.alias(S) == "acct-1"  # the sender moves the most
    assert f.alias(T1) == "acct-2"  # then the biggest receiver
    assert CaseFacts(fan_out_case()).alias(T3) == f.alias(T3)
    assert f.resolve("acct-1") == S and f.resolve(S) == S and f.resolve("acct-99") is None
    assert f.dealias_text("acct-1 paid acct-2; acct-10 and acct-1x stay") == (
        f"{S} paid {T1}; acct-10 and acct-1x stay"
    )


def test_alias_prefix_avoids_collision_with_real_ids():
    case = make_case([make_edge("acct-1", "acct-2", 1, 10.0)])
    f = CaseFacts(case)
    assert f.alias_prefix != "acct-"
    assert f.resolve(f.alias("acct-1")) == "acct-1"


def test_count_and_amount_values():
    f = CaseFacts(fan_out_case())
    assert f.count_value("n_members", None, None) == 5
    assert f.count_value("n_transfers", None, None) == 10
    assert f.count_value("n_edges", None, None) == 4
    assert f.count_value("out_degree", "acct-1", None) == 4
    assert f.count_value("in_degree", "acct-1", None) == 0
    assert f.count_value("edge_n_transfers", "acct-1", "acct-2") == 4
    assert f.count_value("edge_n_transfers", "acct-2", "acct-1") is None  # no such edge
    assert f.count_value("out_degree", "acct-77", None) is None
    assert f.amount_value("ring_total_inr", None, None) == pytest.approx(699978.27)
    assert f.amount_value("account_out_inr", "acct-1", None) == pytest.approx(699978.27)
    assert f.amount_value("account_in_inr", "acct-2", None) == 338392.79
    assert f.amount_value("max_edge_inr", None, None) == 338392.79
    assert f.amount_value("edge_total_inr", "acct-1", "acct-3") == 254020.59


@pytest.mark.parametrize(
    ("edges", "shape"),
    [
        ("fan_out", "fan_out"),
        ("cycle", "cycle"),
        ("chain", "chain"),
    ],
)
def test_structural_pattern(edges, shape):
    lookup = {"fan_out": fan_out_case()["edges"], "cycle": CYCLE, "chain": CHAIN}
    assert CaseFacts(make_case(lookup[edges])).structural_pattern() == shape


def test_fan_in_gather_scatter_and_unclear():
    fan_in = [make_edge(x, "9Z0000009", 1, 10.0 + i) for i, x in enumerate(["a1", "a2", "a3"])]
    assert CaseFacts(make_case(fan_in)).structural_pattern() == "fan_in"
    gs = [make_edge(x, "HUB000001", 1, 5.0) for x in ("a1", "a2")] + [
        make_edge("HUB000001", y, 1, 4.0) for y in ("b1", "b2")
    ]
    assert CaseFacts(make_case(gs)).structural_pattern() == "gather_scatter"
    assert CaseFacts(make_case([], members=["x", "y", "z"])).structural_pattern() == "unclear"
    two_cycle = [make_edge("p1", "p2", 1, 5.0), make_edge("p2", "p1", 1, 5.0)]
    assert not CaseFacts(make_case(two_cycle)).has_cycle()  # needs three accounts


def test_coverage_levels():
    assert CaseFacts(fan_out_case()).coverage == "full"
    assert CaseFacts(fan_out_case(edges_truncated=True)).coverage == "partial"
    assert CaseFacts(fan_out_case(members_truncated=True)).coverage == "partial"
    assert CaseFacts(fan_out_case(edges_available=False)).coverage == "none"


def test_stats_use_aliases_only_and_are_json():
    f = CaseFacts(fan_out_case())
    text = json.dumps(f.stats() | {"top": f.top_accounts()})
    for real in (S, T1, T2, T3, T4):
        assert real not in text
    stats = f.stats()
    assert stats["structure"] == "fan_out" and stats["n_edges"] == 4
    assert stats["max_out_degree"] == {"account": "acct-1", "value": 4}
    assert stats["n_pure_sources"] == 1 and stats["n_pure_sinks"] == 4
    assert stats["top_sender"]["share_pct"] == 100.0
    assert stats["span_hours"] == pytest.approx(67.0, abs=0.2)  # 09-04 04:52 to 09-06 23:44


def test_tools_return_aliases_and_respect_limits():
    box = ToolBox(CaseFacts(fan_out_case()))
    out = box.call("edge_weights", {"top_n": 2})
    assert [e["to"] for e in out["edges"]] == ["acct-2", "acct-3"]
    assert out["top_share_pct"] == pytest.approx(84.6, abs=0.05)
    by_count = box.call("edge_weights", {"top_n": 1, "by": "n_transfers"})
    assert by_count["edges"][0]["n_transfers"] == 4
    nb = box.call("get_neighbors", {"account": "acct-1", "direction": "out", "limit": 3})
    assert nb["out_degree"] == 4 and nb["rows_total"] == 4 and nb["rows_shown"] == 3
    assert box.call("get_neighbors", {"account": "acct-2"})["in_degree"] == 1
    tl = box.call("get_timeline", {"account": None, "limit": 10})
    firsts = [e["first_ts"] for e in tl["edges_in_time_order"]]
    assert firsts == sorted(firsts) and tl["n_edges"] == 4
    assert box.call("get_timeline", {"account": "acct-2"})["n_edges"] == 1
    stats = box.call("community_stats", {})
    assert stats["top_accounts"][0]["account"] == "acct-1"
    blob = json.dumps([out, nb, tl, stats])
    assert all(real not in blob for real in (S, T1, T2, T3, T4))


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("delete_everything", {}),
        ("edge_weights", {"top_n": 0}),
        ("edge_weights", {"top_n": MAX_ROWS + 1}),
        ("edge_weights", {"top_n": True}),
        ("edge_weights", {"top_n": "3"}),
        ("edge_weights", {"by": "score"}),
        ("edge_weights", {"extra": 1}),
        ("community_stats", {"account": "acct-1"}),
        ("get_neighbors", {}),
        ("get_neighbors", {"account": S}),  # real ids are not accepted, only aliases
        ("get_neighbors", {"account": "acct-99"}),
        ("get_neighbors", {"account": "acct-1", "direction": "sideways"}),
        ("get_timeline", {"account": 5}),
        ("get_timeline", {"limit": -1}),
        ("get_timeline", "not an object"),
    ],
)
def test_tools_reject_bad_calls(name, args):
    with pytest.raises(ToolError):
        ToolBox(CaseFacts(fan_out_case())).call(name, args)


def test_tool_names_are_exactly_the_four_in_the_plan():
    assert set(TOOL_NAMES) == {"get_neighbors", "get_timeline", "edge_weights", "community_stats"}


def test_tools_on_a_case_without_edges_are_empty_not_errors():
    box = ToolBox(CaseFacts(make_case([], members=[A, B, C], edges_available=False)))
    assert box.call("edge_weights", {})["edges"] == []
    assert box.call("get_timeline", {})["edges_in_time_order"] == []
    assert box.call("community_stats", {})["coverage"] == "none"


def test_cycle_stats_flag_the_cycle():
    stats = CaseFacts(make_case(CYCLE)).stats()
    assert stats["has_cycle_of_3_or_more"] is True and stats["structure"] == "cycle"
    assert stats["n_relays"] == 3
