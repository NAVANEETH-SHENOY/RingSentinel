"""Stage 08 hardening: auth-failure lockout, proxy-aware client address, body size, headers."""

import pytest
from app.config import AppSettings, load_app_settings
from app.main import create_app
from app.ratelimit import MAX_TRACKED_KEYS, WINDOW_SECONDS, RateLimiter
from fastapi.testclient import TestClient
from ringsentinel.config import Settings
from ringsentinel.snapshots.export import export_snapshots
from s04_bundle import write_stage03_outputs

TOKEN = "t" * 24
GOOD = {"X-Analyst-Token": TOKEN}
BAD = {"X-Analyst-Token": "x" * 24}
RID = "R-" + "0" * 12


def action(n=1):
    return {"action": "confirm", "analyst": "asha", "note": "", "idempotency_key": f"k{n:018d}"}


@pytest.fixture(scope="module")
def snapshot_dir(tmp_path_factory):
    root = tmp_path_factory.mktemp("hard")
    s = Settings(data_dir=root / "data")
    write_stage03_outputs(s)
    return export_snapshots(s, root / "snap", git_commit="deadbeef").directory


def build(snapshot_dir, tmp_path, now=None, **overrides):
    values = {
        "snapshot_dir": snapshot_dir, "analyst_token": TOKEN,
        "audit_db_url": f"sqlite:///{(tmp_path / 'a.sqlite3').as_posix()}",
        "rate_limit_read_per_min": 0, "rate_limit_write_per_min": 0,
    }  # fmt: skip
    values.update(overrides)
    clock = {"clock": lambda: now[0]} if now is not None else {}
    return TestClient(create_app(AppSettings(**values), **clock))


# ---------------------------------------------------------------- auth failure lockout
def test_repeated_bad_tokens_lock_the_client_out_then_recover(snapshot_dir, tmp_path):
    now = [0.0]
    client = build(snapshot_dir, tmp_path, now, rate_limit_authfail_per_min=3)
    assert [client.get("/api/v1/audit", headers=BAD).status_code for _ in range(3)] == [401] * 3
    locked = client.get("/api/v1/audit", headers=GOOD)  # even the right token waits
    assert locked.status_code == 429 and int(locked.headers["Retry-After"]) >= 1
    assert client.get("/api/v1/health").status_code == 429
    now[0] = WINDOW_SECONDS + 1
    assert client.get("/api/v1/audit", headers=GOOD).status_code == 200


def test_good_requests_never_fill_the_failure_bucket(snapshot_dir, tmp_path):
    client = build(snapshot_dir, tmp_path, rate_limit_authfail_per_min=2)
    assert all(client.get("/api/v1/audit", headers=GOOD).status_code == 200 for _ in range(10))


def test_other_status_codes_do_not_count_as_auth_failures(snapshot_dir, tmp_path):
    client = build(snapshot_dir, tmp_path, rate_limit_authfail_per_min=2)
    for _ in range(6):
        assert client.get("/api/v1/cases/R-" + "f" * 12).status_code == 404
        assert client.get("/api/v1/queue", params={"limit": 0}).status_code == 422
    assert client.get("/api/v1/health").status_code == 200


def test_authfail_bucket_can_be_turned_off(snapshot_dir, tmp_path):
    client = build(snapshot_dir, tmp_path, rate_limit_authfail_per_min=0)
    assert all(client.get("/api/v1/audit", headers=BAD).status_code == 401 for _ in range(30))


# ---------------------------------------------------------------- proxy-aware address
def test_forwarded_header_is_ignored_without_a_trusted_proxy(snapshot_dir, tmp_path):
    """A client cannot dodge its limit by inventing X-Forwarded-For."""
    client = build(snapshot_dir, tmp_path, rate_limit_read_per_min=2)
    codes = [
        client.get("/api/v1/health", headers={"X-Forwarded-For": f"203.0.113.{i}"}).status_code
        for i in range(4)
    ]
    assert codes == [200, 200, 429, 429]


def test_with_one_trusted_proxy_the_last_entry_is_the_client(snapshot_dir, tmp_path):
    client = build(snapshot_dir, tmp_path, rate_limit_read_per_min=1, trusted_proxy_hops=1)

    def hit(real_client, forged="9.9.9.9"):
        return client.get(
            "/api/v1/health", headers={"X-Forwarded-For": f"{forged}, {real_client}"}
        ).status_code

    assert hit("198.51.100.1") == 200
    assert hit("198.51.100.1", forged="8.8.8.8") == 429  # forging the left entry changes nothing
    assert hit("198.51.100.2") == 200  # a different real client has its own allowance


def test_garbage_or_short_forwarded_header_falls_back_to_the_peer(snapshot_dir, tmp_path):
    client = build(snapshot_dir, tmp_path, rate_limit_read_per_min=1, trusted_proxy_hops=2)
    assert client.get("/api/v1/health", headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 200
    # only one entry but two proxies are trusted: ignored, so the peer's allowance is used up
    assert client.get("/api/v1/health", headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 429
    other = build(snapshot_dir, tmp_path, rate_limit_read_per_min=1, trusted_proxy_hops=1)
    assert other.get("/api/v1/health", headers={"X-Forwarded-For": "not-an-ip"}).status_code == 200
    assert other.get("/api/v1/health", headers={"X-Forwarded-For": "also-bad"}).status_code == 429


# ---------------------------------------------------------------- body size
def test_oversized_body_is_refused_before_the_route_runs(snapshot_dir, tmp_path):
    client = build(snapshot_dir, tmp_path, max_body_bytes=1024)
    big = {**action(), "note": "x" * 2000}
    response = client.post(f"/api/v1/cases/{RID}/action", json=big, headers=GOOD)
    assert response.status_code == 413
    assert client.get("/api/v1/audit/verify").json()["entries"] == 0


def test_normal_action_still_passes_the_size_check(snapshot_dir, tmp_path):
    client = build(snapshot_dir, tmp_path)
    response = client.post(f"/api/v1/cases/{RID}/action", json=action(), headers=GOOD)
    assert response.status_code == 404  # a valid body reaches the route (no such ring)


def test_chunked_and_malformed_length_bodies_are_refused(snapshot_dir, tmp_path):
    client = build(snapshot_dir, tmp_path)
    url = f"/api/v1/cases/{RID}/action"
    chunked = client.post(url, content=iter([b'{"a":', b"1}"]), headers=GOOD)
    assert chunked.status_code == 411
    bad = client.post(url, content=b"{}", headers={**GOOD, "Content-Length": "12abc"})
    assert bad.status_code in (400, 422)  # the HTTP stack may refuse it first


# ---------------------------------------------------------------- headers and docs
def test_security_headers_on_every_response_class(snapshot_dir, tmp_path):
    client = build(snapshot_dir, tmp_path)
    for response in (
        client.get("/api/v1/health"),
        client.get("/api/v1/audit", headers=BAD),
        client.get("/api/v1/cases/R-" + "f" * 12),
        client.post(f"/api/v1/cases/{RID}/action", json=action(), headers=GOOD),
    ):
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "no-referrer"


def test_rate_limited_and_oversized_responses_also_carry_the_headers(snapshot_dir, tmp_path):
    client = build(snapshot_dir, tmp_path, rate_limit_read_per_min=1, max_body_bytes=1024)
    client.get("/api/v1/health")
    limited = client.get("/api/v1/health")
    assert limited.status_code == 429 and limited.headers["x-content-type-options"] == "nosniff"
    big = client.post(f"/api/v1/cases/{RID}/action", json={**action(), "note": "x" * 4000})
    assert big.status_code in (413, 429) and big.headers["x-frame-options"] == "DENY"


def test_audit_and_writes_are_not_cached(snapshot_dir, tmp_path):
    client = build(snapshot_dir, tmp_path)
    assert client.get("/api/v1/audit", headers=GOOD).headers["cache-control"] == "no-store"
    posted = client.post(f"/api/v1/cases/{RID}/action", json=action(), headers=GOOD)
    assert posted.headers["cache-control"] == "no-store"
    assert "cache-control" not in client.get("/api/v1/health").headers


def test_docs_can_be_switched_off(snapshot_dir, tmp_path):
    on = build(snapshot_dir, tmp_path)
    off = build(snapshot_dir, tmp_path, docs_enabled=False)
    assert on.get("/api/docs").status_code == 200
    assert off.get("/api/docs").status_code == 404
    assert off.get("/api/openapi.json").status_code == 404
    assert off.get("/api/v1/health").status_code == 200


# ---------------------------------------------------------------- settings
def test_settings_validation_and_environment(monkeypatch, tmp_path):
    base = {"snapshot_dir": tmp_path, "audit_db_url": "sqlite:///x"}
    for bad in ({"trusted_proxy_hops": 6}, {"trusted_proxy_hops": -1}, {"max_body_bytes": 10},
                {"max_body_bytes": 5_000_000}, {"rate_limit_authfail_per_min": -1}):  # fmt: skip
        with pytest.raises(ValueError):
            AppSettings(**base, **bad)
    monkeypatch.setenv("RS_TRUSTED_PROXY_HOPS", "1")
    monkeypatch.setenv("RS_MAX_BODY_BYTES", "4096")
    monkeypatch.setenv("RS_RATE_LIMIT_AUTHFAIL_PER_MIN", "5")
    monkeypatch.setenv("RS_API_DOCS", "off")
    settings = load_app_settings(load_env_file=False)
    assert (settings.trusted_proxy_hops, settings.max_body_bytes) == (1, 4096)
    assert settings.rate_limit_authfail_per_min == 5 and settings.docs_enabled is False
    monkeypatch.setenv("RS_API_DOCS", "yes")
    assert load_app_settings(load_env_file=False).docs_enabled is True


def test_secure_defaults():
    s = AppSettings(snapshot_dir="x", audit_db_url="sqlite:///x")
    assert s.trusted_proxy_hops == 0 and s.max_body_bytes == 16_384
    assert s.rate_limit_authfail_per_min == 10 and s.docs_enabled is True


# ---------------------------------------------------------------- limiter internals
def test_blocked_and_record_do_not_interfere_with_check():
    now = [0.0]
    lim = RateLimiter({"authfail": 2, "read": 5}, clock=lambda: now[0])
    assert lim.blocked("a", "authfail") is None
    lim.record("a", "authfail")
    assert lim.blocked("a", "authfail") is None
    lim.record("a", "authfail")
    assert lim.blocked("a", "authfail") == pytest.approx(WINDOW_SECONDS)
    assert lim.blocked("b", "authfail") is None
    now[0] = WINDOW_SECONDS
    assert lim.blocked("a", "authfail") is None


def test_limiter_memory_stays_bounded_under_a_flood_of_fresh_clients():
    now = [0.0]
    lim = RateLimiter({"read": 1}, clock=lambda: now[0])
    for i in range(MAX_TRACKED_KEYS * 3):
        lim.check(f"c{i}", "read")
    assert len(lim._hits) <= MAX_TRACKED_KEYS
