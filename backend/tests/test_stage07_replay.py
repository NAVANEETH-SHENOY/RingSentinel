"""Replay engine (Stage 07, data stage D11): ring timing, latency, timeline, determinism."""

import json

import numpy as np
import pandas as pd
import pytest
from ringsentinel.config import Settings
from ringsentinel.monitor.replay import (
    MIN_TRUTH_SHARE,
    NS_PER_MINUTE,
    build_replay_document,
    compute_replay,
    ring_timing,
)
from ringsentinel.snapshots.bundle import validate_document

T0 = int(pd.Timestamp("2022-09-10 00:00").value)
MIN = NS_PER_MINUTE


def at(minute):
    return T0 + minute * MIN


def ring(rid, rank=1):
    return {"ring_id": rid, "rank": rank, "score": 0.5, "expected_value_inr": 1000.0 - rank,
            "n_members": 3, "n_transfers": 4}  # fmt: skip


def events(minutes, src, dst, truth=None, ids=None):
    n = len(minutes)
    return {
        "ts_ns": np.array([at(m) for m in minutes], dtype="int64"), "src": list(src),
        "dst": list(dst), "event_id": np.array(ids if ids is not None else range(n)),
        "truth_id": list(truth) if truth is not None else [-1] * n,
    }  # fmt: skip


RID_A, RID_B = "R-" + "a" * 12, "R-" + "b" * 12


# --------------------------------------------------------------- ring timing
def test_a_ring_is_detected_when_its_transfers_first_touch_the_minimum_size():
    # accounts seen: {a,b} after t=0, {a,b,c} after t=10 -> detected at minute 10
    ts = np.array([at(0), at(5), at(10), at(30)])
    first, found, partial = ring_timing(
        ts, ["a", "a", "b", "c"], ["b", "b", "c", "d"], np.arange(4), 3
    )  # fmt: skip
    assert (first, found, partial) == (at(0), at(10), False)


def test_unsorted_input_is_walked_in_time_order_with_event_id_tiebreak():
    ts = np.array([at(10), at(0), at(0)])
    ids = np.array([9, 2, 1])
    first, found, partial = ring_timing(ts, ["b", "a", "a"], ["c", "b", "c"], ids, 3)
    assert first == at(0) and found == at(0) and partial is False  # event 1 (a->c) then 2 (a->b)


def test_a_ring_that_never_reaches_the_size_is_partial_at_its_last_transfer():
    ts = np.array([at(0), at(7)])
    assert ring_timing(ts, ["a", "a"], ["b", "b"], np.arange(2), 3) == (at(0), at(7), True)


# --------------------------------------------------------------- hand-computed replay
TEST_MINUTES = [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20]  # 11 test events, two minutes apart
TEST_TS = np.array([at(m) for m in TEST_MINUTES], dtype="int64")


def doc_for(ring_events, rings=None, truth_first=None, **kw):
    rings = rings or [ring(RID_A, 1), ring(RID_B, 2)]
    kw.setdefault("n_steps", 10)
    return compute_replay(
        rings, ring_events, TEST_TS, truth_first or {}, detector="xgb_graph", threshold=0.05,
        min_size=3, **kw,
    )


def test_hand_computed_assembly_and_truth_latency():
    ring_events = {
        # first flagged transfer at minute 4, third account appears at minute 10
        RID_A: events([4, 6, 10, 12], "aabc", "bbcd", truth=[7, 7, 7, 7]),
        RID_B: events([14, 16], "xx", "yz", truth=[-1, -1]),
    }
    doc = doc_for(ring_events, truth_first={7: at(2)})
    a, b = doc["events"][0], doc["events"][1]
    assert a["ring_id"] == RID_A and a["first_ts"] == pd.Timestamp(at(4)).isoformat()
    assert a["detected_ts"] == pd.Timestamp(at(10)).isoformat() and a["partial"] is False
    assert a["assembly_minutes"] == 6.0
    assert a["assembly_events"] == 3  # test events at minutes 4, 6, 8 lie in [4, 10)
    assert a["truth_ring_id"] == 7 and a["truth_share"] == 1.0
    assert a["latency_minutes"] == 8.0  # detected at 10, the true ring started at 2
    assert a["latency_events"] == 4  # events at minutes 2, 4, 6, 8
    assert b["ring_id"] == RID_B and b["detected_ts"] == pd.Timestamp(at(16)).isoformat()
    assert b["latency_minutes"] is None and b["truth_ring_id"] is None
    assert b["assembly_minutes"] == 2.0 and b["assembly_events"] == 1


def test_summary_statistics_by_hand():
    ring_events = {
        RID_A: events([4, 6, 10], "aab", "bbc", truth=[7, 7, 7]),
        RID_B: events([14, 16], "xx", "yz"),
    }
    doc = doc_for(ring_events, truth_first={7: at(2)})
    s = doc["summary"]
    assert s["n_rings"] == 2 and s["n_with_truth"] == 1 and s["n_partial"] == 0
    assert s["assembly_minutes_median"] == pytest.approx(4.0)  # (6 + 2) / 2
    assert s["latency_minutes_median"] == 8.0 and s["latency_events_median"] == 4.0
    assert s["n_test_events"] == 11


def test_latency_needs_a_majority_true_ring_and_a_detection_after_its_start():
    mixed = events([4, 6, 10, 12], "aabc", "bbcd", truth=[7, 3, 3, -1])  # id 3 wins with 2 of 4
    doc = doc_for({RID_A: mixed}, rings=[ring(RID_A)], truth_first={3: at(2), 7: at(0)})
    assert doc["events"][0]["truth_ring_id"] == 3 and doc["events"][0]["truth_share"] == 0.5
    weak = events([4, 6, 10, 12], "aabc", "bbcd", truth=[7, 3, 5, -1])  # best share 0.25
    doc = doc_for({RID_A: weak}, rings=[ring(RID_A)], truth_first={3: at(2), 7: at(0), 5: at(1)})
    assert doc["events"][0]["latency_minutes"] is None and MIN_TRUTH_SHARE == 0.5
    early = events([4, 6, 10], "aab", "bbc", truth=[7, 7, 7])
    doc = doc_for({RID_A: early}, rings=[ring(RID_A)], truth_first={7: at(18)})  # starts later
    assert doc["events"][0]["latency_minutes"] is None  # detection before the true ring began


def test_a_truth_tie_goes_to_the_smaller_id():
    two = events([4, 6, 10, 12], "aabc", "bbcd", truth=[9, 9, 4, 4])
    doc = doc_for({RID_A: two}, rings=[ring(RID_A)], truth_first={9: at(0), 4: at(0)})
    assert doc["events"][0]["truth_ring_id"] == 4


def test_events_are_listed_in_detection_order_with_ring_id_tiebreak():
    both = {
        RID_B: events([4, 6, 8], "aab", "bbc"),
        RID_A: events([4, 6, 8], "aab", "bbc"),
        "R-" + "c" * 12: events([0, 2, 4], "aab", "bbc"),
    }
    rings = [ring(RID_A, 1), ring(RID_B, 2), ring("R-" + "c" * 12, 3)]
    doc = doc_for(both, rings=rings)
    assert [e["ring_id"] for e in doc["events"]] == ["R-" + "c" * 12, RID_A, RID_B]


def test_rings_without_transfers_are_skipped():
    doc = doc_for({RID_A: events([4, 6, 10], "aab", "bbc")}, rings=[ring(RID_A), ring(RID_B, 2)])
    assert [e["ring_id"] for e in doc["events"]] == [RID_A]
    doc = doc_for({RID_A: events([], "", "")}, rings=[ring(RID_A)])
    assert doc["events"] == [] and doc["summary"]["assembly_minutes_median"] is None


# --------------------------------------------------------------- timeline
def test_timeline_buckets_add_up():
    ring_events = {
        RID_A: events([4, 6, 10], "aab", "bbc"), RID_B: events([14, 16, 18], "xxy", "yzz"),
    }
    doc = doc_for(ring_events, n_steps=5)
    tl = doc["timeline"]
    assert tl["n_steps"] == 5 and tl["step_minutes"] == pytest.approx(4.0)
    assert tl["start_ts"] == pd.Timestamp(at(0)).isoformat()
    assert sum(tl["events"]) == 11 and sum(tl["ring_transfers"]) == 6
    assert sum(tl["detected"]) == 2
    assert tl["events"] == [2, 2, 2, 2, 3]  # [0,4) [4,8) [8,12) [12,16) [16,20] last bucket closed
    assert len(tl["events"]) == len(tl["ring_transfers"]) == len(tl["detected"]) == 5


def test_replay_is_deterministic_and_valid_against_the_schema():
    ring_events = {
        RID_A: events([4, 6, 10, 12], "aabc", "bbcd", truth=[7] * 4),
        RID_B: events([14, 16, 18], "xxy", "yzz"),
    }
    a = doc_for(ring_events, truth_first={7: at(2)})
    b = doc_for(dict(reversed(ring_events.items())), truth_first={7: at(2)})
    dump = {"sort_keys": True, "allow_nan": False}
    assert json.dumps(a, **dump) == json.dumps(b, **dump)
    validate_document("replay.json", a)
    assert a["status"] == "ready" and a["min_ring_members"] == 3 and a["notes"]


def test_no_test_events_gives_an_empty_but_valid_document():
    doc = compute_replay([], {}, np.array([], dtype="int64"), {}, detector="d", threshold=None,
                         min_size=3, n_steps=10)  # fmt: skip
    assert doc["events"] == [] and sum(doc["timeline"]["events"]) == 0
    validate_document("replay.json", doc)


# --------------------------------------------------------------- reading the parquet files
def write_inputs(settings):
    """Eight test events; accounts a1..a3 form ring 1, b1..b3 ring 2; ring_id column = truth."""
    settings.processed_dir.mkdir(parents=True, exist_ok=True)
    rows = [  # event_id, minute, src, dst, truth ring id (None for noise), split
        (0, 0, "n1", "n2", None, "train"),
        (1, 10, "a1", "a2", 5, "test"), (2, 12, "n1", "n2", None, "test"),
        (3, 14, "a2", "a3", 5, "test"), (4, 20, "b1", "b2", 6, "test"),
        (5, 22, "n3", "n4", None, "test"), (6, 30, "b2", "b3", 6, "test"),
        (7, 40, "n3", "n4", None, "test"),
    ]  # fmt: skip
    ev = pd.DataFrame(rows, columns=["event_id", "minute", "src_account", "dst_account",
                                     "ring_id", "split"])  # fmt: skip
    ev["ts"] = pd.Timestamp("2022-09-10") + pd.to_timedelta(ev["minute"], unit="m")
    ev["ring_id"] = ev["ring_id"].astype("Int32")
    ev[["event_id", "ts", "src_account", "dst_account", "ring_id"]].to_parquet(
        settings.events_path, index=False
    )  # fmt: skip
    ev[["event_id", "split"]].to_parquet(settings.split_path, index=False)


KEPT = [
    ("R-" + "1" * 12, 1, 900.0, {"event_ids": [1, 3], "score": 0.9, "n_members": 3,
                                 "n_transfers": 2}),
    ("R-" + "2" * 12, 2, 800.0, {"event_ids": [4, 6], "score": 0.8, "n_members": 3,
                                 "n_transfers": 2}),
]  # fmt: skip


def test_reading_the_parquet_files_gives_the_hand_values(tmp_path):
    settings = Settings(data_dir=tmp_path, replay_steps=10)
    write_inputs(settings)
    doc = build_replay_document(settings, KEPT, detector="xgb_graph", threshold=0.05)
    assert doc["status"] == "ready" and doc["min_ring_members"] == 3
    one, two = doc["events"]
    assert one["ring_id"] == "R-" + "1" * 12
    assert one["first_ts"] == "2022-09-10T00:10:00"
    assert one["detected_ts"] == "2022-09-10T00:14:00"
    assert one["assembly_minutes"] == 4.0 and one["assembly_events"] == 2  # minutes 10 and 12
    assert one["truth_ring_id"] == 5 and one["latency_minutes"] == 4.0
    assert one["latency_events"] == 2
    assert two["detected_ts"] == "2022-09-10T00:30:00" and two["latency_minutes"] == 10.0
    assert doc["summary"]["n_test_events"] == 7  # the train event is not part of the test period
    assert sum(doc["timeline"]["events"]) == 7
    validate_document("replay.json", doc)
    assert build_replay_document(settings, KEPT, detector="xgb_graph", threshold=0.05) == doc


def test_missing_files_give_none_so_the_placeholder_stays(tmp_path):
    assert build_replay_document(Settings(data_dir=tmp_path), KEPT, detector="d",
                                 threshold=0.05) is None  # fmt: skip
