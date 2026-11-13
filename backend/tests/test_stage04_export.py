"""Snapshot exporter (D12): ranking arithmetic, determinism, schemas, hashes, edges."""

import json
import shutil

import pytest
from ringsentinel.config import Settings
from ringsentinel.snapshots.bundle import (
    DATA_FILES,
    SnapshotError,
    canonical_text,
    load_bundle,
    sha256_bytes,
)
from ringsentinel.snapshots.export import (
    build_documents,
    expected_value_inr,
    export_snapshots,
    ring_id_for,
)
from s04_bundle import EXPECTED_VALUES, RINGS, write_stage03_outputs


@pytest.fixture
def settings(tmp_path):
    s = Settings(data_dir=tmp_path / "data")
    write_stage03_outputs(s)
    return s


def _ids(bundle):
    by_name = {}
    for item in bundle.queue["items"]:
        for name, (members, *_rest) in RINGS.items():
            if item["n_members"] == len(members) and item["score"] == RINGS[name][1]:
                by_name[name] = item["ring_id"]
    return by_name


def test_expected_value_hand_cases():
    assert expected_value_inr(0.9, 100000.0, 3, 250.0, 500.0, 1.0) == 89600.0
    assert expected_value_inr(0.5, 20000.0, 4, 250.0, 500.0, 1.0) == 8750.0
    assert expected_value_inr(0.1, 1000.0, 3, 250.0, 500.0, 1.0) == -1500.0
    # capture scales only the loss term
    assert expected_value_inr(1.0, 1000.0, 5, 250.0, 500.0, 0.5) == 250.0
    assert expected_value_inr(0.0, 1000.0, 2, 0.0, 100.0, 1.0) == -200.0


def test_queue_is_ranked_by_expected_value_with_exact_numbers(settings, tmp_path):
    bundle = export_snapshots(settings, tmp_path / "out")
    ids = _ids(bundle)
    items = bundle.queue["items"]
    assert [i["ring_id"] for i in items] == [ids["A"], ids["B"], ids["C"]]
    assert [i["rank"] for i in items] == [1, 2, 3]
    assert [i["expected_value_inr"] for i in items] == [
        EXPECTED_VALUES["A"], EXPECTED_VALUES["B"], EXPECTED_VALUES["C"],
    ]  # fmt: skip
    assert all(len(i["top_features"]) == 3 for i in items)  # queue shows the top three only
    assert all(len(c["top_features"]) == 5 for c in bundle.cases["cases"].values())
    assert bundle.queue["score_calibrated"] is False


def test_ring_id_depends_on_members_and_detector_but_not_member_order():
    assert ring_id_for("d", ["x", "y", "z"]) == ring_id_for("d", ["z", "x", "y"])
    assert ring_id_for("d", ["x", "y", "z"]) != ring_id_for("d", ["x", "y", "w"])
    assert ring_id_for("d", ["x", "y"]) != ring_id_for("e", ["x", "y"])
    assert ring_id_for("d", ["x"]).startswith("R-") and len(ring_id_for("d", ["x"])) == 14


def test_export_is_byte_deterministic_even_from_a_copy_of_the_inputs(settings, tmp_path):
    first = export_snapshots(settings, tmp_path / "one", git_commit="abc")
    second = export_snapshots(settings, tmp_path / "two", git_commit="abc")
    copy_root = tmp_path / "copy"
    shutil.copytree(settings.data_dir, copy_root)
    third = export_snapshots(Settings(data_dir=copy_root), tmp_path / "three", git_commit="abc")
    for name in (*DATA_FILES, "meta.json"):
        a = (first.directory / name).read_bytes()
        assert a == (second.directory / name).read_bytes()
        assert a == (third.directory / name).read_bytes()
    assert first.bundle_id == second.bundle_id == third.bundle_id


def test_bundle_id_changes_when_an_input_number_changes(settings, tmp_path):
    before = export_snapshots(settings, tmp_path / "a").bundle_id
    path = settings.metrics_path
    doc = json.loads(path.read_text())
    doc["detectors"]["xgb_graph"]["test"]["pr_auc"] = 0.6
    path.write_text(json.dumps(doc))
    assert export_snapshots(settings, tmp_path / "b").bundle_id != before


def test_git_commit_and_frozen_flag_are_recorded_and_change_only_meta(settings, tmp_path):
    a = export_snapshots(settings, tmp_path / "a", git_commit="aaa", frozen=False)
    b = export_snapshots(settings, tmp_path / "b", git_commit="bbb", frozen=True)
    assert a.meta["git_commit"] == "aaa" and a.meta["evaluation_frozen"] is False
    assert b.meta["git_commit"] == "bbb" and b.meta["evaluation_frozen"] is True
    assert a.bundle_id == b.bundle_id  # the data files themselves are identical


def test_max_rings_keeps_the_best_ranked_and_reports_the_total(settings, tmp_path):
    bundle = export_snapshots(settings, tmp_path / "out", max_rings=2)
    assert bundle.meta["n_rings_total"] == 3 and bundle.meta["n_rings_exported"] == 2
    assert [i["rank"] for i in bundle.queue["items"]] == [1, 2]
    assert len(bundle.cases["cases"]) == 2
    with pytest.raises(ValueError):
        build_documents(settings, max_rings=0)


def test_edges_are_aggregated_per_account_pair_and_sorted(settings, tmp_path):
    bundle = export_snapshots(settings, tmp_path / "out")
    case_a = bundle.cases["cases"][_ids(bundle)["A"]]
    assert case_a["edges_available"] is True and case_a["edges_truncated"] is False
    assert case_a["edges"] == [
        {"src": "a1", "dst": "a2", "n_transfers": 2, "total_inr": 150.0,
         "first_ts": "2022-09-01T10:00:00", "last_ts": "2022-09-01T11:00:00"},
        {"src": "a2", "dst": "a3", "n_transfers": 1, "total_inr": 10.0,
         "first_ts": "2022-09-01T12:00:00", "last_ts": "2022-09-01T12:00:00"},
    ]  # fmt: skip
    case_c = bundle.cases["cases"][_ids(bundle)["C"]]
    assert [e["dst"] for e in case_c["edges"]] == ["c2"]  # event 7 is not in ring C


def test_without_events_the_cases_say_edges_are_unavailable(settings, tmp_path):
    bundle = export_snapshots(settings, tmp_path / "out", with_edges=False)
    for case in bundle.cases["cases"].values():
        assert case["edges"] == [] and case["edges_available"] is False


def test_edges_truncated_is_flagged_when_the_ring_has_more_transfers_than_listed(tmp_path):
    s = Settings(data_dir=tmp_path / "data")
    rings = {"A": (["a1", "a2", "a3"], 0.9, 1000.0, [1, 2, 3])}
    write_stage03_outputs(s, rings)
    doc = json.loads(s.rings_path.read_text())
    doc["rings"][0]["n_transfers"] = 900  # rings.json caps event_ids at 500
    s.rings_path.write_text(json.dumps(doc))
    case = next(iter(export_snapshots(s, tmp_path / "o").cases["cases"].values()))
    assert case["edges_truncated"] is True


def test_members_truncated_when_rings_json_listed_fewer_members_than_the_ring_has(tmp_path):
    s = Settings(data_dir=tmp_path / "data")
    write_stage03_outputs(s, {"A": (["a1", "a2", "a3"], 0.9, 1000.0, [1, 2, 3])})
    doc = json.loads(s.rings_path.read_text())
    doc["rings"][0]["n_members"] = 700
    s.rings_path.write_text(json.dumps(doc))
    case = next(iter(export_snapshots(s, tmp_path / "o").cases["cases"].values()))
    assert case["members_truncated"] is True and case["members"] == ["a1", "a2", "a3"]


def test_placeholders_for_stages_not_built_yet(settings, tmp_path):
    bundle = export_snapshots(settings, tmp_path / "out")
    assert bundle.drift["status"] == "not_built" and bundle.drift["built_in_stage"] == "07"
    assert bundle.replay["status"] == "not_built" and bundle.replay["events"] == []
    for case in bundle.cases["cases"].values():
        assert case["ai"]["status"] == "not_built" and case["ai"]["built_in_stage"] == "06"


def test_no_rings_exports_an_empty_but_valid_bundle_with_the_note(tmp_path):
    s = Settings(data_dir=tmp_path / "data")
    write_stage03_outputs(s, rings={})
    doc = json.loads(s.rings_path.read_text())
    doc["threshold"], doc["note"] = float("nan"), "The validation rule chose to flag nothing."
    s.rings_path.write_text(json.dumps(doc))  # json.dumps writes NaN, as numpy-based code can
    bundle = export_snapshots(s, tmp_path / "o")
    assert bundle.queue["items"] == [] and bundle.queue["threshold"] is None
    assert "flag nothing" in bundle.queue["note"]


def test_missing_stage03_output_is_a_clear_error(settings, tmp_path):
    settings.latency_path.unlink()
    with pytest.raises(SnapshotError, match="latency.json"):
        export_snapshots(settings, tmp_path / "out")


def test_output_files_use_the_canonical_form(settings, tmp_path):
    bundle = export_snapshots(settings, tmp_path / "out")
    for name in DATA_FILES:
        text = (bundle.directory / name).read_text(encoding="utf-8")
        assert text.endswith("\n") and "\r" not in text
        assert text == canonical_text(json.loads(text))
        assert bundle.meta["files"][name] == sha256_bytes(text.encode("utf-8"))


# ------------------------------------------------------------ loader refuses bad bundles
def _fresh(settings, tmp_path):
    return export_snapshots(settings, tmp_path / "out").directory


def test_loader_rejects_a_missing_folder_and_a_missing_file(settings, tmp_path):
    with pytest.raises(SnapshotError, match="not found"):
        load_bundle(tmp_path / "nope")
    folder = _fresh(settings, tmp_path)
    (folder / "drift.json").unlink()
    with pytest.raises(SnapshotError, match="drift.json"):
        load_bundle(folder)


def test_loader_detects_an_edited_file_by_its_hash(settings, tmp_path):
    folder = _fresh(settings, tmp_path)
    path = folder / "metrics.json"
    path.write_text(path.read_text().replace("0.5", "0.9", 1), encoding="utf-8")
    with pytest.raises(SnapshotError, match="hash mismatch.*metrics.json"):
        load_bundle(folder)


def test_loader_rejects_schema_violations_before_hashes(settings, tmp_path):
    folder = _fresh(settings, tmp_path)
    doc = json.loads((folder / "queue.json").read_text())
    doc["items"][0]["ring_id"] = "not-a-ring"
    (folder / "queue.json").write_text(json.dumps(doc))
    with pytest.raises(SnapshotError, match="queue.json violates its schema"):
        load_bundle(folder)


def test_loader_rejects_invalid_json(settings, tmp_path):
    folder = _fresh(settings, tmp_path)
    (folder / "replay.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(SnapshotError, match="not valid JSON"):
        load_bundle(folder)


def test_loader_rejects_a_queue_and_cases_that_disagree(settings, tmp_path):
    from ringsentinel.snapshots.bundle import bundle_id_from

    folder = _fresh(settings, tmp_path)
    cases = json.loads((folder / "cases.json").read_text())
    cases["cases"].pop(next(iter(cases["cases"])))
    text = canonical_text(cases)
    (folder / "cases.json").write_bytes(text.encode("utf-8"))
    meta = json.loads((folder / "meta.json").read_text())  # keep hashes consistent on purpose
    meta["files"]["cases.json"] = sha256_bytes(text.encode("utf-8"))
    meta["bundle_id"] = bundle_id_from(meta["files"])
    (folder / "meta.json").write_text(canonical_text(meta), encoding="utf-8")
    with pytest.raises(SnapshotError, match="do not list the same rings"):
        load_bundle(folder)
