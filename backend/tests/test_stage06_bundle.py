"""Stage 06 end to end on a real exported bundle: merge, re-export, stale blocks, API, script."""

import copy
import json

import pytest
from app.config import AppSettings
from app.main import create_app
from fastapi.testclient import TestClient
from ringsentinel.ai.pipeline import ai_document, build_ai_cases
from ringsentinel.ai.provider import make_provider
from ringsentinel.config import Settings, get_settings
from ringsentinel.snapshots.ai_merge import merge_ai_into_bundle
from ringsentinel.snapshots.bundle import SnapshotError, canonical_text, load_bundle
from ringsentinel.snapshots.export import export_snapshots
from ringsentinel.stage06 import format_report, run_ai
from s04_bundle import write_stage03_outputs

NON_AI = ("ring_id", "rank", "score", "expected_value_inr", "amount_inr", "n_members",
          "n_transfers", "oversized", "members", "members_truncated", "top_features", "edges",
          "edges_available", "edges_truncated")  # fmt: skip


@pytest.fixture
def settings(tmp_path):
    s = Settings(data_dir=tmp_path / "data")
    write_stage03_outputs(s)
    export_snapshots(s)
    return s


def snapshot_bytes(directory):
    return {p.name: p.read_bytes() for p in sorted(directory.glob("*.json"))}


def test_run_ai_merges_blocks_and_changes_only_the_ai_field(settings):
    before = load_bundle(settings.snapshots_dir)
    queue_bytes = (settings.snapshots_dir / "queue.json").read_bytes()
    report = run_ai(settings, provider_name="fake", limit=None)
    after = load_bundle(settings.snapshots_dir)  # schema, hashes and cross checks all pass
    assert (settings.snapshots_dir / "queue.json").read_bytes() == queue_bytes
    for rid, case in after.cases["cases"].items():
        old = before.cases["cases"][rid]
        assert {k: case[k] for k in NON_AI} == {k: old[k] for k in NON_AI}
        assert case["ai"]["status"] == "ready" and case["ai"]["verifier"]["status"] == "verified"
        assert case["ai"]["provider"] == {"name": "fake", "model": "heuristic-v1"}
    assert after.bundle_id != before.bundle_id and after.bundle_id == report["bundle_id_after"]
    assert "ai_cases.json" in after.meta["sources"]
    assert report["merge"] == {"applied": 3, "stale": 0, "missing": 0}
    assert report["by_source"] == {"llm": 3, "cache": 0, "template": 0}
    assert report["verified_share_of_llm_attempted"] == 1.0
    assert settings.ai_cases_path.is_file() and settings.ai_report_path.is_file()
    assert "verified share             100.0%" in format_report(report)


def test_offline_run_gives_every_case_a_verified_template(settings):
    report = run_ai(settings, provider_name="none")
    assert report["by_source"] == {"llm": 0, "cache": 0, "template": 3}
    assert report["verified_share_of_llm_attempted"] is None
    assert "n/a" in format_report(report)
    for case in load_bundle(settings.snapshots_dir).cases["cases"].values():
        assert case["ai"]["source"] == "template"
        assert case["ai"]["verifier"]["status"] == "verified"


def test_second_run_is_served_from_cache_and_is_byte_identical(settings):
    run_ai(settings, provider_name="fake", limit=None)
    first = snapshot_bytes(settings.snapshots_dir)
    report = run_ai(settings, provider_name="fake", limit=None)
    assert report["by_source"] == {"llm": 0, "cache": 3, "template": 0}
    second = snapshot_bytes(settings.snapshots_dir)
    # cache hits are marked source "cache", so cases.json differs only in that field
    assert (
        second["queue.json"]
        == first["queue.json"]
        == (settings.snapshots_dir / "queue.json").read_bytes()
    )
    assert json.loads(second["cases.json"].decode()) != json.loads(first["cases.json"].decode())
    third = run_ai(settings, provider_name="fake", limit=None)
    assert third["by_source"]["cache"] == 3 and snapshot_bytes(settings.snapshots_dir) == second


def test_no_apply_leaves_the_bundle_untouched(settings):
    before = snapshot_bytes(settings.snapshots_dir)
    report = run_ai(settings, provider_name="fake", limit=None, apply=False)
    assert snapshot_bytes(settings.snapshots_dir) == before and "merge" not in report
    assert settings.ai_cases_path.is_file()


def test_reexport_keeps_the_ai_blocks(settings):
    run_ai(settings, provider_name="fake", limit=None)
    rebuilt = export_snapshots(settings)  # Stage 04 exporter run again
    assert all(c["ai"]["status"] == "ready" for c in rebuilt.cases["cases"].values())
    assert "ai_cases.json" in rebuilt.meta["sources"]
    again = export_snapshots(settings)
    assert again.bundle_id == rebuilt.bundle_id  # still deterministic


def test_stale_blocks_are_left_out_not_applied(settings):
    run_ai(settings, provider_name="fake", limit=None)
    rings = json.loads(settings.rings_path.read_text(encoding="utf-8"))
    rings["rings"][0]["score"] = 0.55  # the detector output changed after the AI ran
    settings.rings_path.write_text(json.dumps(rings), encoding="utf-8")
    rebuilt = export_snapshots(settings)
    states = sorted(c["ai"]["status"] for c in rebuilt.cases["cases"].values())
    assert states == ["not_built", "ready", "ready"]


def test_a_tampered_ai_block_is_refused_before_anything_is_written(settings):
    run_ai(settings, provider_name="fake", limit=None, apply=False)
    doc = json.loads(settings.ai_cases_path.read_text(encoding="utf-8"))
    rid = sorted(doc["cases"])[0]
    before = snapshot_bytes(settings.snapshots_dir)
    for tamper in ({"score": 0.0}, {"action": "dismiss"}):
        bad = copy.deepcopy(doc)
        bad["cases"][rid].update(tamper)
        with pytest.raises(SnapshotError, match="violates its schema"):
            merge_ai_into_bundle(settings.snapshots_dir, bad)
        assert snapshot_bytes(settings.snapshots_dir) == before
    bad = copy.deepcopy(doc)
    bad["cases"][rid]["verifier"]["status"] = "trusted"
    with pytest.raises(SnapshotError):
        merge_ai_into_bundle(settings.snapshots_dir, bad)
    bad = copy.deepcopy(doc)
    bad["cases"][rid]["investigator"] = None  # a ready block must carry a case file
    with pytest.raises(SnapshotError):
        merge_ai_into_bundle(settings.snapshots_dir, bad)


def test_ai_output_can_never_alter_a_detector_score(settings):
    """The whole path from model output to bundle leaves score, rank and value as they were."""
    bundle = load_bundle(settings.snapshots_dir)
    cases = bundle.cases["cases"]
    blocks, _ = build_ai_cases(cases, make_provider("fake"), None)
    merged, _ = merge_ai_into_bundle(settings.snapshots_dir, ai_document(blocks))
    for rid, case in merged.cases["cases"].items():
        assert case["score"] == cases[rid]["score"] and case["rank"] == cases[rid]["rank"]
        assert case["expected_value_inr"] == cases[rid]["expected_value_inr"]
    assert canonical_text(merged.queue) == canonical_text(bundle.queue)
    queue_scores = [i["score"] for i in merged.queue["items"]]
    assert queue_scores == [i["score"] for i in bundle.queue["items"]]


def test_api_serves_the_ai_block_and_still_starts(settings, tmp_path):
    run_ai(settings, provider_name="fake", limit=None)
    app = create_app(
        AppSettings(
            snapshot_dir=settings.snapshots_dir, analyst_token="t" * 24,
            audit_db_url=f"sqlite:///{(tmp_path / 'audit.sqlite3').as_posix()}",
            rate_limit_read_per_min=0, rate_limit_write_per_min=0,
        )
    )  # fmt: skip
    client = TestClient(app)
    first = client.get("/api/v1/queue").json()["items"][0]["ring_id"]
    case = client.get(f"/api/v1/cases/{first}").json()
    assert case["ai"]["status"] == "ready" and case["ai"]["verifier"]["status"] == "verified"
    assert case["ai"]["investigator"]["pattern"] and "score" not in case["ai"]


def test_edited_cases_file_after_merge_stops_the_bundle_loading(settings):
    run_ai(settings, provider_name="fake", limit=None)
    path = settings.snapshots_dir / "cases.json"
    path.write_text(path.read_text(encoding="utf-8").replace("fake", "real"), encoding="utf-8")
    with pytest.raises(SnapshotError, match="hash mismatch"):
        load_bundle(settings.snapshots_dir)


def test_settings_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("RS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RS_LLM_PROVIDER", "Groq")
    monkeypatch.setenv("RS_LLM_MODEL", "some-model")
    monkeypatch.setenv("RS_LLM_MAX_TOOL_CALLS", "4")
    monkeypatch.setenv("RS_AI_MAX_LLM_CASES", "7")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_SECRET_VALUE")
    s = get_settings(load_env_file=False)
    assert (s.llm_provider, s.llm_model, s.llm_max_tool_calls, s.ai_max_llm_cases) == (
        "groq", "some-model", 4, 7,
    )  # fmt: skip
    assert "gsk_SECRET_VALUE" not in repr(s) and "gsk_SECRET_VALUE" not in s.model_dump_json()
    assert s.ai_cases_path.name == "ai_cases.json" and s.ai_cache_dir.name == "ai_cache"


@pytest.mark.parametrize(
    "bad",
    [
        {"llm_provider": "openai"},
        {"llm_timeout_s": 0},
        {"llm_min_interval_s": -1},
        {"llm_max_tool_calls": 11},
        {"llm_verify_retries": 6},
        {"ai_max_llm_cases": -1},
    ],
)
def test_bad_ai_settings_are_refused(bad):
    with pytest.raises(ValueError):
        Settings(**bad)


def test_command_line_script(settings, monkeypatch, capsys):
    import run_stage06

    monkeypatch.setenv("RS_DATA_DIR", str(settings.data_dir))
    assert run_stage06.main(["--provider", "fake", "--all"]) == 0
    out = capsys.readouterr().out
    assert "verified share             100.0%" in out and "ai_cases.json" in out
    monkeypatch.setenv("GROQ_API_KEY", "")
    assert run_stage06.main(["--provider", "groq", "--refresh"]) == 1
    assert "GROQ_API_KEY" in capsys.readouterr().out
    assert run_stage06.main(["--snapshots", str(settings.data_dir / "nowhere")]) == 1


def test_ai_query_script(settings, monkeypatch, capsys):
    import ai_query

    monkeypatch.setenv("RS_DATA_DIR", str(settings.data_dir))
    run_ai(settings, provider_name="fake", limit=None)
    assert (
        ai_query.main(["--dsl", '{"filters": [{"field": "rank", "op": "lte", "value": 2}]}']) == 0
    )
    out = capsys.readouterr().out
    assert "2 ring(s)" in out and "ai llm/verified" in out
    assert ai_query.main(["--dsl", '{"filters": [{"field": "nope", "op": "eq", "value": 1}]}']) == 1
    assert ai_query.main(["which rings are contested", "--provider", "fake"]) == 0
    assert "0 ring(s)" in capsys.readouterr().out
