"""Live queue, feedback state and the scripted analyst scenario (Stage 07), through the API."""

import pytest
from app.config import AppSettings, load_app_settings
from app.main import create_app
from fastapi.testclient import TestClient
from ringsentinel.review.feedback import HARD_MAX_OFFSET
from s07_world import build_bundle, build_world

TOKEN = "t" * 24
H = {"X-Analyst-Token": TOKEN}


def key(n):
    return f"idem-key-{n:012d}"


def act(client, ring_id, action, n, note="checked"):
    return client.post(
        f"/api/v1/cases/{ring_id}/action", headers=H,
        json={"action": action, "analyst": "asha", "note": note, "idempotency_key": key(n)},
    )  # fmt: skip


@pytest.fixture(scope="module")
def snap(tmp_path_factory):
    root = tmp_path_factory.mktemp("s07api")
    settings = build_world(root)
    return build_bundle(settings, root / "snap").directory


def make_client(snap, tmp_path, **overrides):
    values = {
        "snapshot_dir": snap, "analyst_token": TOKEN,
        "audit_db_url": f"sqlite:///{(tmp_path / 'audit.sqlite3').as_posix()}",
        "rate_limit_read_per_min": 0, "rate_limit_write_per_min": 0,
    }  # fmt: skip
    values.update(overrides)
    return TestClient(create_app(AppSettings(**values)))


@pytest.fixture
def client(snap, tmp_path):
    return make_client(snap, tmp_path)


def ring_ids(client):
    return [i["ring_id"] for i in client.get("/api/v1/queue").json()["items"]]


def test_default_queue_order_is_the_exported_order_and_has_status_and_live(client):
    out = client.get("/api/v1/queue").json()
    assert out["order"] == "export" and out["feedback"]["n_pending"] == len(out["items"])
    ranks = [i["rank"] for i in out["items"]]
    assert ranks == sorted(ranks)
    assert all(i["status"] == "pending" and "live" in i for i in out["items"])


def test_with_no_decisions_live_values_equal_the_exported_values(client):
    for i in client.get("/api/v1/queue").json()["items"]:
        assert i["live"]["adjusted_score"] == pytest.approx(i["score"], abs=1e-12)
        assert i["live"]["adjusted_expected_value_inr"] == pytest.approx(
            i["expected_value_inr"], rel=1e-9, abs=1e-6)  # fmt: skip


def test_feedback_endpoint_matches_the_queue_state(client):
    fb = client.get("/api/v1/feedback").json()
    q = client.get("/api/v1/queue").json()
    assert fb["offset_logit"] == 0 and fb["validated"] is False
    assert {k: v for k, v in fb.items() if k != "bundle_id"} == q["feedback"]
    assert fb["bundle_id"] == q["bundle_id"]


def test_bad_order_value_is_rejected(client):
    assert client.get("/api/v1/queue?order=sideways").status_code == 422


def test_dismissals_raise_the_threshold_and_stop_at_the_bound(client):
    ids = ring_ids(client)
    base = client.get("/api/v1/feedback").json()["base_threshold"]
    seen = []
    for n, rid in enumerate(ids, start=1):
        assert act(client, rid, "dismiss", n).status_code in (200, 201)
        fb = client.get("/api/v1/feedback").json()
        seen.append(fb["offset_logit"])
        assert 0 <= fb["offset_logit"] <= fb["max_offset_logit"] <= HARD_MAX_OFFSET
        if base is not None and fb["effective_threshold"] is not None:
            assert fb["effective_threshold"] >= base
    assert seen == sorted(seen) and seen[-1] <= 1.5


def test_confirmations_never_lower_the_threshold_below_base(client):
    ids = ring_ids(client)
    for n, rid in enumerate(ids[:3], start=1):
        act(client, rid, "confirm", n)
    fb = client.get("/api/v1/feedback").json()
    assert fb["offset_logit"] == 0
    assert fb["effective_threshold"] == fb["base_threshold"]


def test_decided_rings_move_to_the_bottom_of_the_live_order(client):
    ids = ring_ids(client)
    act(client, ids[0], "confirm", 1)
    live = client.get("/api/v1/queue?order=live").json()
    assert live["order"] == "live"
    assert live["items"][-1]["ring_id"] == ids[0]
    assert live["items"][-1]["live"]["live_rank"] is None
    assert [i["ring_id"] for i in client.get("/api/v1/queue").json()["items"]] == ids


def test_held_rings_stay_open_and_do_not_move_the_threshold(client):
    rid = ring_ids(client)[0]
    act(client, rid, "hold", 1)
    fb = client.get("/api/v1/feedback").json()
    assert fb["n_held"] == 1 and fb["offset_logit"] == 0
    live = {i["ring_id"]: i for i in client.get("/api/v1/queue?order=live").json()["items"]}
    assert live[rid]["status"] == "held"


def test_scripted_scenario_queue_case_act_audit_replay(client):
    # 1. open the queue
    queue = client.get("/api/v1/queue").json()
    assert queue["items"]
    rid = queue["items"][0]["ring_id"]
    # 2. open the case
    case = client.get(f"/api/v1/cases/{rid}").json()
    assert case["ring_id"] == rid and case["ai"]["status"] in ("ready", "not_built")
    # 3. act, with and without the token
    assert client.post(f"/api/v1/cases/{rid}/action", json={}).status_code in (401, 403, 422)
    first = act(client, rid, "confirm", 1)
    assert first.status_code in (200, 201)
    again = act(client, rid, "confirm", 1)  # idempotent retry
    assert again.json()["replayed"] is True and first.json()["replayed"] is False
    assert again.json()["entry"] == first.json()["entry"]
    assert act(client, rid, "dismiss", 2).status_code == 409  # decided is closed
    # 4. the audit entry is there and the chain verifies
    audit = client.get("/api/v1/audit", headers=H).json()
    entries = audit["entries"] if isinstance(audit, dict) else audit
    assert len(entries) == 1 and entries[0]["ring_id"] == rid and entries[0]["action"] == "confirm"
    assert client.get("/api/v1/audit/verify", headers=H).json()["ok"] is True
    # 5. replay and drift are served, deterministic across calls
    replay = client.get("/api/v1/replay").json()
    assert replay["status"] == "ready" and replay["events"]
    assert client.get("/api/v1/replay").json() == replay
    assert client.get("/api/v1/drift").json()["status"] == "ready"
    # 6. the queue now shows the decision
    items = {i["ring_id"]: i for i in client.get("/api/v1/queue").json()["items"]}
    assert items[rid]["status"] == "confirmed"


def test_feedback_settings_are_read_from_the_environment(monkeypatch, tmp_path):
    for name in ("RS_FEEDBACK_STEP", "RS_FEEDBACK_MAX_OFFSET", "RS_FEEDBACK_CONFIRM_WEIGHT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RS_FEEDBACK_STEP", "0.2")
    monkeypatch.setenv("RS_FEEDBACK_MAX_OFFSET", "2.0")
    monkeypatch.setenv("RS_FEEDBACK_CONFIRM_WEIGHT", "0.5")
    s = load_app_settings(load_env_file=False)
    cfg = s.feedback_config()
    assert (cfg.step, cfg.max_offset, cfg.confirm_weight) == (0.2, 2.0, 0.5)


@pytest.mark.parametrize("name,value", [
    ("RS_FEEDBACK_MAX_OFFSET", "99"), ("RS_FEEDBACK_STEP", "-1"),
    ("RS_FEEDBACK_CONFIRM_WEIGHT", "50"), ("RS_FEEDBACK_STEP", "nan"),
])  # fmt: skip
def test_settings_beyond_the_hard_ceilings_are_refused(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(Exception):  # noqa: B017 - ValueError or pydantic ValidationError
        load_app_settings(load_env_file=False)


def test_a_custom_small_bound_is_honoured(snap, tmp_path):
    c = make_client(snap, tmp_path, feedback_max_offset=0.15, feedback_step=0.1)
    for n, rid in enumerate(ring_ids(c), start=1):
        act(c, rid, "dismiss", n)
    fb = c.get("/api/v1/feedback").json()
    assert fb["offset_logit"] <= 0.15 and fb["at_bound"] is (fb["offset_logit"] >= 0.15)
