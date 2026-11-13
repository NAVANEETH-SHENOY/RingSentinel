"""Stage 03 outputs on the synthetic world -> snapshot bundle -> API -> actions -> audit."""

import importlib.util
import json
from pathlib import Path

import pytest
from app.config import AppSettings
from app.main import create_app
from fastapi.testclient import TestClient
from ringsentinel import stage02, stage03
from ringsentinel.config import Settings
from ringsentinel.snapshots.export import export_snapshots
from s03_world import write_world

TOKEN = "integration-token-0123"
H = {"X-Analyst-Token": TOKEN}
SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "export_snapshots.py"


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    root = tmp_path_factory.mktemp("s04world")
    settings = Settings(data_dir=root / "data")
    write_world(settings)
    stage02.run_features(settings)
    stage03.run_detect(settings)
    stage03.run_evaluate(settings)
    stage03.run_ablate(settings)
    stage03.run_robustness(settings)
    return settings, root


@pytest.fixture(scope="module")
def bundle(pipeline):
    settings, root = pipeline
    return export_snapshots(settings, root / "snap", git_commit="cafe")


def test_every_ring_of_stage_03_reaches_the_queue_with_real_edges(pipeline, bundle):
    settings, _ = pipeline
    rings = json.loads(settings.rings_path.read_text())["rings"]
    assert bundle.meta["n_rings_total"] == len(rings) == len(bundle.queue["items"])
    assert bundle.meta["evaluation_frozen"] is False
    for case in bundle.cases["cases"].values():
        assert case["edges_available"] and case["edges"]
        accounts = set(case["members"])
        assert {e["src"] for e in case["edges"]} <= accounts
        assert {e["dst"] for e in case["edges"]} <= accounts
        assert sum(e["n_transfers"] for e in case["edges"]) == case["n_transfers"]
    values = [i["expected_value_inr"] for i in bundle.queue["items"]]
    assert values == sorted(values, reverse=True)


def test_metrics_in_the_bundle_equal_the_stage_03_files(pipeline, bundle):
    settings, _ = pipeline
    source = json.loads(settings.metrics_path.read_text())
    assert bundle.metrics["detectors"] == json.loads(json.dumps(source["detectors"]))
    assert bundle.metrics["ablations"] == json.loads(settings.ablations_path.read_text())


def test_a_full_analyst_session_over_http(pipeline, bundle, tmp_path):
    client = TestClient(
        create_app(
            AppSettings(
                snapshot_dir=bundle.directory, analyst_token=TOKEN,
                audit_db_url=f"sqlite:///{(tmp_path / 'audit.sqlite3').as_posix()}",
                rate_limit_read_per_min=0, rate_limit_write_per_min=0,
            )
        )
    )  # fmt: skip
    queue = client.get("/api/v1/queue", params={"limit": 500}).json()
    first, second = queue["items"][0]["ring_id"], queue["items"][1]["ring_id"]
    case = client.get(f"/api/v1/cases/{first}").json()
    assert case["rank"] == 1 and case["edges"]
    one = client.post(f"/api/v1/cases/{first}/action", headers=H, json={
        "action": "confirm", "analyst": "asha", "note": "ring is real",
        "idempotency_key": "session-key-000000001"})  # fmt: skip
    two = client.post(f"/api/v1/cases/{second}/action", headers=H, json={
        "action": "dismiss", "analyst": "asha", "note": "family account",
        "idempotency_key": "session-key-000000002"})  # fmt: skip
    assert (one.status_code, two.status_code) == (201, 201)
    items = client.get("/api/v1/queue", params={"limit": 500}).json()["items"]
    after = {i["ring_id"]: i["status"] for i in items}
    assert after[first] == "confirmed" and after[second] == "dismissed"
    verify = client.get("/api/v1/audit/verify").json()
    assert verify["ok"] and verify["entries"] == 2
    assert client.get("/api/v1/metrics").json()["bundle_id"] == bundle.bundle_id


def test_export_script_runs_and_matches_the_library_output(
    pipeline, bundle, tmp_path, monkeypatch, capsys
):
    settings, _ = pipeline
    monkeypatch.setenv("RS_DATA_DIR", str(settings.data_dir))
    monkeypatch.delenv("RS_DATASET_VARIANT", raising=False)
    spec = importlib.util.spec_from_file_location("export_snapshots_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    out = tmp_path / "cli"
    assert module.main(["--out", str(out), "--git-commit", "cafe"]) == 0
    printed = capsys.readouterr().out
    assert bundle.bundle_id in printed and "evaluation_frozen = False" in printed
    for name in ("queue.json", "cases.json", "metrics.json", "meta.json"):
        assert (out / name).read_bytes() == (bundle.directory / name).read_bytes()


def test_export_script_reports_a_missing_stage_03_output_without_a_traceback(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("RS_DATA_DIR", str(tmp_path / "empty"))
    monkeypatch.delenv("RS_DATASET_VARIANT", raising=False)
    spec = importlib.util.spec_from_file_location("export_snapshots_cli2", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main(["--out", str(tmp_path / "x")]) == 1
    assert "EXPORT FAILED" in capsys.readouterr().out
