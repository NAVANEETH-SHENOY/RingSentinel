import pandas as pd
import pytest
from ringsentinel.graph.ablation import attribute_links, format_ablation_table, giant_component_rows
from ringsentinel.graph.build import build_graph
from toy_events import make_events

COLS = ["src_account", "dst_account", "ts", "amount_inr"]


def _world():
    # 20 separate two-account pairs, joined only through one hub account Z, plus an
    # unrelated 3-account chain (the unambiguous giant once Z is removed)
    rows = [("c0", "c1", 200, 5.0), ("c1", "c2", 201, 5.0)]
    for i in range(20):
        rows.append((f"a{i:02d}", f"b{i:02d}", i, 10.0))
        rows.append(("Z", f"a{i:02d}", 100 + i, 1.0))
    return make_events(rows)


def _noise(graph, shared_vpa=True):
    accounts = list(graph.accounts)
    return pd.DataFrame(
        {
            "account": accounts,
            "derived_ip_id": range(1000, 1000 + len(accounts)),
            "derived_device_id": range(5000, 5000 + len(accounts)),
            "derived_vpa_handle_id": [0] * len(accounts) if shared_vpa else range(len(accounts)),
        }
    )


def test_hub_control_breaks_the_hub_made_giant_component():
    graph = build_graph(_world()[COLS], hub_cap=10)
    rows = {r["variant"]: r for r in giant_component_rows(graph, _noise(graph), "val", 10, 200)}
    assert rows["transfer_no_control"]["giant_size"] == 41  # everything hangs off Z
    assert rows["transfer_controlled"]["giant_size"] == 3
    assert rows["transfer_controlled"]["hub_accounts_dropped"] == 1
    assert rows["transfer_controlled"]["components"] == 20 + 1 + 1  # pairs, chain, isolated Z


def test_a_shared_derived_attribute_collapses_everything_until_capped():
    graph = build_graph(_world()[COLS], hub_cap=10)
    rows = {r["variant"]: r for r in giant_component_rows(graph, _noise(graph), "val", 10, 200)}
    assert rows["transfer_plus_noise_no_control"]["giant_size"] == graph.n
    assert rows["transfer_plus_noise_no_control"]["components"] == 1
    controlled = rows["transfer_plus_noise_controlled"]
    assert controlled["attribute_values_dropped"] == 1  # the single shared VPA handle
    assert controlled["giant_size"] == 3


def test_rows_report_ring_account_share_when_given():
    graph = build_graph(_world()[COLS], hub_cap=10)
    ring = pd.Index(graph.accounts).get_indexer(["a00", "b00"])
    rows = giant_component_rows(graph, _noise(graph), "val", 10, 200, ring_nodes=ring)
    assert all("ring_accounts_in_giant_share" in r for r in rows)
    assert rows[0]["ring_accounts_in_giant_share"] == 1.0  # inside the Z-made giant
    # a00-b00 is a separate pair, outside the chain-made giant
    assert rows[1]["ring_accounts_in_giant_share"] == 0.0


def test_noise_must_cover_every_account():
    graph = build_graph(_world()[COLS], hub_cap=10)
    with pytest.raises(ValueError, match="missing accounts"):
        attribute_links(graph, _noise(graph).iloc[:5], 10)


def test_table_formats():
    graph = build_graph(_world()[COLS], hub_cap=10)
    text = format_ablation_table(giant_component_rows(graph, _noise(graph), "val", 10, 200))
    assert "transfer_controlled" in text and text.count("\n") == 4
