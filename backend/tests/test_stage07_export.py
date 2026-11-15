"""Exporter with drift and replay (Stage 07): schema, determinism, fallbacks, tamper checks."""

import json

import pytest
from ringsentinel.snapshots.bundle import SnapshotError, load_bundle
from ringsentinel.snapshots.export import export_snapshots
from s07_world import build_bundle, build_world


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("s07export")
    settings = build_world(root)
    return settings, root


@pytest.fixture(scope="module")
def bundle(world):
    settings, root = world
    return build_bundle(settings, root / "snap")


def test_drift_and_replay_are_built_when_their_inputs_exist(bundle):
    assert bundle.drift["status"] == "ready" and bundle.drift["built_in_stage"] == "07"
    assert bundle.replay["status"] == "ready" and bundle.replay["built_in_stage"] == "07"
    assert bundle.drift["detector"] == bundle.queue["detector"] == "xgb_graph"
    assert bundle.drift["threshold"] == bundle.queue["threshold"]
    assert len(bundle.drift["windows"]) == 8 and bundle.drift["reference"]["split"] == "val"
    assert bundle.drift["summary"]["n_test"] == sum(w["n_events"] for w in bundle.drift["windows"])


def test_replay_only_names_rings_that_are_in_the_queue(bundle):
    queue_ids = {i["ring_id"] for i in bundle.queue["items"]}
    replayed = [e["ring_id"] for e in bundle.replay["events"]]
    assert replayed and set(replayed) <= queue_ids and len(set(replayed)) == len(replayed)
    by_id = {i["ring_id"]: i for i in bundle.queue["items"]}
    for e in bundle.replay["events"]:
        item = by_id[e["ring_id"]]
        assert e["rank"] == item["rank"] and e["score"] == item["score"]
        assert e["first_ts"] <= e["detected_ts"] and e["assembly_minutes"] >= 0
    detected = [e["detected_ts"] for e in bundle.replay["events"]]
    assert detected == sorted(detected)


def test_replay_timeline_counts_every_test_event_and_every_detection(bundle):
    tl = bundle.replay["timeline"]
    assert sum(tl["events"]) == bundle.replay["summary"]["n_test_events"]
    assert sum(tl["events"]) == bundle.drift["summary"]["n_test"]
    assert sum(tl["detected"]) == len(bundle.replay["events"])


def test_the_whole_bundle_is_byte_identical_on_a_second_export(world, bundle):
    settings, root = world
    again = build_bundle(settings, root / "snap2")
    for name in ("drift.json", "replay.json", "queue.json", "cases.json", "meta.json"):
        assert (root / "snap" / name).read_bytes() == (root / "snap2" / name).read_bytes(), name
    assert again.bundle_id == bundle.bundle_id


def test_the_bundle_id_covers_drift_and_replay(world, bundle):
    settings, root = world
    placeholder = build_bundle(settings, root / "snap_nomon", with_monitor=False)
    assert placeholder.drift["status"] == "not_built"
    assert placeholder.replay["status"] == "not_built"
    assert placeholder.bundle_id != bundle.bundle_id
    assert placeholder.meta["files"]["queue.json"] == bundle.meta["files"]["queue.json"]
    assert placeholder.meta["files"]["drift.json"] != bundle.meta["files"]["drift.json"]


def test_missing_scores_leave_drift_a_placeholder_but_replay_still_builds(world):
    settings, root = world
    scores = settings.scores_path
    saved = scores.read_bytes()
    scores.unlink()
    try:
        out = build_bundle(settings, root / "snap_noscores")
        assert out.drift["status"] == "not_built" and out.replay["status"] == "ready"
    finally:
        scores.write_bytes(saved)


def test_missing_events_leave_both_as_placeholders(world):
    settings, root = world
    out = build_bundle(settings, root / "snap_noevents", with_edges=False)
    assert out.drift["status"] == "ready"  # drift reads events itself, not the edges option
    events = settings.events_path
    saved = events.read_bytes()
    events.unlink()
    try:
        out = build_bundle(settings, root / "snap_noevents2")
        assert out.drift["status"] == "not_built" and out.replay["status"] == "not_built"
    finally:
        events.write_bytes(saved)


def test_editing_drift_or_replay_after_export_breaks_loading(world, bundle):
    _, root = world
    folder = root / "snap_tamper"
    folder.mkdir()
    for name in ("meta.json", "queue.json", "cases.json", "metrics.json", "drift.json",
                 "replay.json"):  # fmt: skip
        (folder / name).write_bytes((root / "snap" / name).read_bytes())
    load_bundle(folder)
    doc = json.loads((folder / "drift.json").read_text())
    doc["windows"][0]["psi"] = 0.0
    (folder / "drift.json").write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(SnapshotError, match="drift.json"):
        load_bundle(folder)


def test_a_ready_document_with_a_missing_field_is_rejected(world, bundle):
    from ringsentinel.snapshots.bundle import validate_document

    doc = json.loads(json.dumps(bundle.drift))
    del doc["summary"]
    with pytest.raises(SnapshotError, match="summary"):
        validate_document("drift.json", doc)
    doc = json.loads(json.dumps(bundle.replay))
    doc["timeline"]["events"] = ["x"]
    with pytest.raises(SnapshotError):
        validate_document("replay.json", doc)
    doc = json.loads(json.dumps(bundle.drift))
    doc["windows"][0]["level"] = "panic"
    with pytest.raises(SnapshotError, match="level"):
        validate_document("drift.json", doc)


def test_the_stage_04_placeholders_are_still_valid(bundle):
    from ringsentinel.snapshots.bundle import validate_document

    validate_document("drift.json", {"schema_version": "1", "status": "not_built",
                                     "built_in_stage": "07", "psi_alert_level": None,
                                     "windows": []})  # fmt: skip
    validate_document("replay.json", {"schema_version": "1", "status": "not_built",
                                      "built_in_stage": "07", "events": []})  # fmt: skip


def test_ai_blocks_and_monitoring_coexist(world, bundle):
    settings, root = world
    from ringsentinel.stage06 import run_ai

    folder = root / "snap_ai"
    export_snapshots(settings, folder, git_commit="cafe")
    run_ai(settings, provider_name="none", snapshots_dir=folder)
    merged = load_bundle(folder)
    assert merged.drift == bundle.drift and merged.replay == bundle.replay
    assert all(c["ai"]["status"] == "ready" for c in merged.cases["cases"].values())
    assert merged.bundle_id != bundle.bundle_id
