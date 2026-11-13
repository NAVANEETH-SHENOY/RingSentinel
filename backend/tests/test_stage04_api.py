"""API contract tests (D13): every endpoint, auth, validation, idempotency, limits, CORS."""

import sqlite3

import pytest
from app.config import AppSettings
from app.main import create_app
from fastapi.testclient import TestClient
from ringsentinel.config import Settings
from ringsentinel.snapshots.bundle import SnapshotError
from ringsentinel.snapshots.export import export_snapshots
from s04_bundle import EXPECTED_VALUES, write_stage03_outputs

TOKEN = "t" * 24
H = {"X-Analyst-Token": TOKEN}


def key(n):
    return f"idem-key-{n:012d}"


def body(action="confirm", n=1, **extra):
    return {"action": action, "analyst": "asha", "note": "looks real", "idempotency_key": key(n),
            **extra}  # fmt: skip


@pytest.fixture(scope="module")
def snapshot_dir(tmp_path_factory):
    root = tmp_path_factory.mktemp("api")
    s = Settings(data_dir=root / "data")
    write_stage03_outputs(s)
    return export_snapshots(s, root / "snap", git_commit="deadbeef").directory


def make_client(snapshot_dir, tmp_path, **overrides):
    values = {
        "snapshot_dir": snapshot_dir, "analyst_token": TOKEN,
        "audit_db_url": f"sqlite:///{(tmp_path / 'audit.sqlite3').as_posix()}",
        "rate_limit_read_per_min": 0, "rate_limit_write_per_min": 0,
    }  # fmt: skip
    values.update(overrides)
    return TestClient(create_app(AppSettings(**values)))


@pytest.fixture
def client(snapshot_dir, tmp_path):
    return make_client(snapshot_dir, tmp_path)


@pytest.fixture
def ids(client):
    items = client.get("/api/v1/queue").json()["items"]
    return {n: i["ring_id"] for n, i in zip("ABC", items, strict=True)}


# ------------------------------------------------------------------ read endpoints
def test_health_reports_the_bundle_and_audit_state(client):
    out = client.get("/api/v1/health").json()
    assert out["status"] == "ok" and out["n_rings"] == 3 and out["audit_entries"] == 0
    assert out["git_commit"] == "deadbeef" and out["evaluation_frozen"] is False
    assert out["actions_enabled"] is True and len(out["bundle_id"]) == 64


def test_queue_contract_and_order(client):
    out = client.get("/api/v1/queue").json()
    assert out["total"] == 3 and out["score_calibrated"] is False
    assert out["detector"] == "xgb_graph" and out["cost_assumptions"]["fp_cost_inr"] == 500.0
    assert [i["expected_value_inr"] for i in out["items"]] == [
        EXPECTED_VALUES["A"], EXPECTED_VALUES["B"], EXPECTED_VALUES["C"],
    ]  # fmt: skip
    assert {i["status"] for i in out["items"]} == {"pending"}
    assert set(out["items"][0]) >= {"ring_id", "rank", "score", "n_members", "top_features"}


def test_queue_paging_and_bounds(client):
    page = client.get("/api/v1/queue", params={"limit": 1, "offset": 1}).json()
    assert page["total"] == 3 and [i["rank"] for i in page["items"]] == [2]
    assert client.get("/api/v1/queue", params={"offset": 99}).json()["items"] == []
    for bad in ({"limit": 0}, {"limit": 501}, {"offset": -1}, {"status": "bogus"}):
        assert client.get("/api/v1/queue", params=bad).status_code == 422


def test_queue_reflects_actions_and_filters_by_status(client, ids):
    client.post(f"/api/v1/cases/{ids['B']}/action", json=body("dismiss"), headers=H)
    client.post(f"/api/v1/cases/{ids['A']}/action", json=body("hold", n=2), headers=H)
    by_status = {s: client.get("/api/v1/queue", params={"status": s}).json() for s in
                 ("pending", "held", "dismissed", "confirmed")}  # fmt: skip
    assert [i["ring_id"] for i in by_status["pending"]["items"]] == [ids["C"]]
    assert [i["ring_id"] for i in by_status["held"]["items"]] == [ids["A"]]
    assert [i["ring_id"] for i in by_status["dismissed"]["items"]] == [ids["B"]]
    assert by_status["confirmed"]["total"] == 0
    full = client.get("/api/v1/queue").json()["items"]
    assert [i["ring_id"] for i in full] == [ids["A"], ids["B"], ids["C"]]  # order never changes


def test_case_contract(client, ids):
    out = client.get(f"/api/v1/cases/{ids['A']}").json()
    assert out["ring_id"] == ids["A"] and out["status"] == "pending" and out["n_actions"] == 0
    assert out["members"] == ["a1", "a2", "a3"] and len(out["edges"]) == 2
    assert out["ai"]["status"] == "not_built" and out["edges_available"] is True


def test_case_unknown_and_malformed_ids(client):
    assert client.get("/api/v1/cases/R-" + "0" * 12).status_code == 404
    for bad in ("nope", "R-XYZ", "R-" + "A" * 12, "R-" + "a" * 13, "..%2F..%2Fetc"):
        assert client.get(f"/api/v1/cases/{bad}").status_code in (404, 422)
    assert client.get("/api/v1/cases/nope").status_code == 422


def test_metrics_drift_and_replay_are_served_from_the_bundle(client):
    metrics = client.get("/api/v1/metrics").json()
    assert metrics["detectors"]["xgb_graph"]["test"]["pr_auc"] == 0.5
    assert metrics["evaluation_frozen"] is False and "ablations" in metrics
    assert metrics["results_table_md"].startswith("| detector")
    drift = client.get("/api/v1/drift").json()
    assert drift["status"] == "not_built" and drift["windows"] == []
    replay = client.get("/api/v1/replay").json()
    assert replay["status"] == "not_built" and replay["events"] == []
    bundle_ids = {client.get(f"/api/v1/{p}").json()["bundle_id"] for p in
                  ("metrics", "drift", "replay", "queue", "health")}  # fmt: skip
    assert len(bundle_ids) == 1


def test_unknown_route_and_wrong_method(client):
    assert client.get("/api/v1/nothing").status_code == 404
    assert client.post("/api/v1/queue").status_code == 405
    assert client.get("/api/openapi.json").status_code == 200


# ------------------------------------------------------------------------ actions
def test_action_requires_a_token(client, ids):
    url = f"/api/v1/cases/{ids['A']}/action"
    assert client.post(url, json=body()).status_code == 401
    assert client.post(url, json=body(), headers={"X-Analyst-Token": "wrong"}).status_code == 401
    assert client.post(url, json=body(), headers={"X-Analyst-Token": ""}).status_code == 401
    assert client.get("/api/v1/audit/verify").json()["entries"] == 0


def test_actions_are_disabled_without_a_configured_token(snapshot_dir, tmp_path):
    client = make_client(snapshot_dir, tmp_path, analyst_token=None)
    assert client.get("/api/v1/health").json()["actions_enabled"] is False
    rid = client.get("/api/v1/queue").json()["items"][0]["ring_id"]
    assert client.post(f"/api/v1/cases/{rid}/action", json=body(), headers=H).status_code == 503
    assert client.get("/api/v1/audit", headers=H).status_code == 503


def test_action_appends_a_chained_entry_and_changes_status(client, ids):
    first = client.post(f"/api/v1/cases/{ids['A']}/action", json=body("hold"), headers=H)
    assert first.status_code == 201
    out = first.json()
    assert out["status"] == "held" and out["replayed"] is False
    assert out["entry"]["seq"] == 1 and out["entry"]["prev_hash"] == "0" * 64
    second = client.post(f"/api/v1/cases/{ids['A']}/action", json=body("confirm", n=2), headers=H)
    assert second.status_code == 201 and second.json()["status"] == "confirmed"
    assert second.json()["entry"]["prev_hash"] == out["entry"]["hash"]
    case = client.get(f"/api/v1/cases/{ids['A']}").json()
    assert case["status"] == "confirmed" and case["n_actions"] == 2
    assert client.get("/api/v1/health").json()["audit_entries"] == 2


def test_action_response_never_echoes_internal_columns(client, ids):
    entry = client.post(f"/api/v1/cases/{ids['A']}/action", json=body(), headers=H).json()["entry"]
    assert "request_sha256" not in entry and entry["analyst"] == "asha"


def test_repeating_the_same_submission_is_safe(client, ids):
    url = f"/api/v1/cases/{ids['A']}/action"
    first = client.post(url, json=body("confirm"), headers=H)
    again = client.post(url, json=body("confirm"), headers=H)
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["replayed"] is True and again.json()["entry"] == first.json()["entry"]
    assert client.get("/api/v1/audit", headers=H).json()["total"] == 1


def test_reusing_a_key_for_a_different_request_conflicts(client, ids):
    client.post(f"/api/v1/cases/{ids['A']}/action", json=body("hold"), headers=H)
    other_action = client.post(f"/api/v1/cases/{ids['A']}/action", json=body("confirm"), headers=H)
    other_ring = client.post(f"/api/v1/cases/{ids['B']}/action", json=body("hold"), headers=H)
    assert other_action.status_code == other_ring.status_code == 409


def test_a_decided_ring_cannot_be_acted_on_again_with_a_new_key(client, ids):
    url = f"/api/v1/cases/{ids['A']}/action"
    assert client.post(url, json=body("dismiss", n=1), headers=H).status_code == 201
    for n, action in enumerate(("confirm", "dismiss", "hold"), start=2):
        res = client.post(url, json=body(action, n=n), headers=H)
        assert res.status_code == 409, action
    assert client.get("/api/v1/audit/verify").json()["entries"] == 1


def test_action_on_an_unknown_ring_is_404_and_writes_nothing(client):
    res = client.post("/api/v1/cases/R-" + "0" * 12 + "/action", json=body(), headers=H)
    assert res.status_code == 404 and client.get("/api/v1/audit/verify").json()["entries"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "delete"}, {"action": "CONFIRM"}, {"action": ""}, {"action": None},
        {"analyst": ""}, {"analyst": "   "}, {"analyst": "x" * 65}, {"analyst": "a\x00b"},
        {"note": "n" * 501}, {"note": "bad\x07"}, {"idempotency_key": "short"},
        {"idempotency_key": "has space in it......"}, {"idempotency_key": "k" * 65},
        {"extra_field": 1}, {"note": 5},
    ],
)  # fmt: skip
def test_invalid_action_bodies_are_rejected_and_write_nothing(client, ids, payload):
    res = client.post(f"/api/v1/cases/{ids['A']}/action", json=body(**payload), headers=H)
    assert res.status_code == 422
    assert client.get("/api/v1/audit/verify").json()["entries"] == 0


def test_missing_fields_and_non_json_bodies_are_rejected(client, ids):
    url = f"/api/v1/cases/{ids['A']}/action"
    assert client.post(url, json={}, headers=H).status_code == 422
    assert client.post(url, json={"action": "hold"}, headers=H).status_code == 422
    assert client.post(url, content=b"not json", headers=H).status_code == 422
    assert client.post(url, json=[1, 2], headers=H).status_code == 422


def test_note_is_optional_and_may_contain_unicode_and_newlines(client, ids):
    payload = {"action": "hold", "analyst": "रवि", "idempotency_key": key(9),
               "note": "line one\nline two ₹"}  # fmt: skip
    res = client.post(f"/api/v1/cases/{ids['A']}/action", json=payload, headers=H)
    assert res.status_code == 201 and res.json()["entry"]["note"] == "line one\nline two ₹"
    minimal = {"action": "hold", "analyst": "x", "idempotency_key": key(10)}
    res = client.post(f"/api/v1/cases/{ids['B']}/action", headers=H, json=minimal)
    assert res.status_code == 201


def test_sql_looking_input_is_stored_as_plain_text(client, ids):
    note = "'; DROP TABLE audit; --"
    res = client.post(f"/api/v1/cases/{ids['A']}/action", json=body(note=note), headers=H)
    assert res.status_code == 201
    entries = client.get("/api/v1/audit", headers=H).json()["entries"]
    assert entries[0]["note"] == note and client.get("/api/v1/audit/verify").json()["ok"]


# ---------------------------------------------------------------------------- audit
def test_audit_list_requires_the_token_and_lists_newest_first(client, ids):
    assert client.get("/api/v1/audit").status_code == 401
    client.post(f"/api/v1/cases/{ids['A']}/action", json=body("hold", n=1), headers=H)
    client.post(f"/api/v1/cases/{ids['B']}/action", json=body("hold", n=2), headers=H)
    out = client.get("/api/v1/audit", headers=H).json()
    assert out["total"] == 2 and [e["seq"] for e in out["entries"]] == [2, 1]
    page = client.get("/api/v1/audit", params={"limit": 1, "offset": 1}, headers=H).json()
    assert [e["seq"] for e in page["entries"]] == [1]
    assert client.get("/api/v1/audit", params={"limit": 501}, headers=H).status_code == 422


def test_audit_verify_is_open_and_detects_tampering(snapshot_dir, tmp_path):
    client = make_client(snapshot_dir, tmp_path)
    rid = client.get("/api/v1/queue").json()["items"][0]["ring_id"]
    client.post(f"/api/v1/cases/{rid}/action", json=body("hold"), headers=H)
    client.post(f"/api/v1/cases/{rid}/action", json=body("confirm", n=2), headers=H)
    good = client.get("/api/v1/audit/verify").json()
    assert good["ok"] is True and good["entries"] == 2 and len(good["head_hash"]) == 64
    raw = sqlite3.connect(tmp_path / "audit.sqlite3")
    raw.execute("UPDATE audit SET note = 'rewritten' WHERE seq = 1")
    raw.commit()
    raw.close()
    bad = client.get("/api/v1/audit/verify").json()
    assert bad["ok"] is False and bad["first_bad_seq"] == 1 and bad["head_hash"] is None


# ---------------------------------------------------------------- limits and CORS
def test_rate_limits_apply_per_bucket_and_recover(snapshot_dir, tmp_path):
    now = [0.0]
    client = TestClient(
        create_app(
            AppSettings(
                snapshot_dir=snapshot_dir, analyst_token=TOKEN,
                audit_db_url=f"sqlite:///{(tmp_path / 'a.sqlite3').as_posix()}",
                rate_limit_read_per_min=3, rate_limit_write_per_min=1,
            ),
            clock=lambda: now[0],
        )
    )  # fmt: skip
    assert [client.get("/api/v1/health").status_code for _ in range(3)] == [200, 200, 200]
    blocked = client.get("/api/v1/health")
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) >= 1
    rid = "R-" + "0" * 12
    assert client.post(f"/api/v1/cases/{rid}/action", json=body(), headers=H).status_code == 404
    assert client.post(f"/api/v1/cases/{rid}/action", json=body(), headers=H).status_code == 429
    now[0] = 61.0
    assert client.get("/api/v1/health").status_code == 200


def test_cors_allows_only_the_configured_origin(snapshot_dir, tmp_path):
    client = make_client(snapshot_dir, tmp_path, cors_origins=("https://app.example.org",))
    ok = client.get("/api/v1/health", headers={"Origin": "https://app.example.org"})
    assert ok.headers["access-control-allow-origin"] == "https://app.example.org"
    other = client.get("/api/v1/health", headers={"Origin": "https://evil.example.org"})
    assert "access-control-allow-origin" not in other.headers
    pre = client.options(
        "/api/v1/cases/R-" + "0" * 12 + "/action",
        headers={"Origin": "https://app.example.org", "Access-Control-Request-Method": "POST",
                 "Access-Control-Request-Headers": "x-analyst-token,content-type"},
    )  # fmt: skip
    allowed = pre.headers["access-control-allow-headers"].lower()
    assert pre.status_code == 200 and "x-analyst-token" in allowed


# ---------------------------------------------------------------------- startup
def test_the_server_refuses_to_start_on_a_tampered_or_missing_bundle(snapshot_dir, tmp_path):
    with pytest.raises(SnapshotError):
        make_client(tmp_path / "does-not-exist", tmp_path)
    copy = tmp_path / "copy"
    copy.mkdir()
    for path in snapshot_dir.iterdir():
        (copy / path.name).write_bytes(path.read_bytes())
    queue = copy / "queue.json"
    queue.write_text(queue.read_text().replace("0.9", "0.8", 1), encoding="utf-8")
    with pytest.raises(SnapshotError, match="hash mismatch"):
        make_client(copy, tmp_path)
