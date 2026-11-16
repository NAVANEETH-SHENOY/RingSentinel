"""scripts/smoke_deployed.py: the deployment smoke test, run against an in-process API and a
fake static site, so every pass and every failure path is exercised without a network."""

import json

import pytest
import smoke_deployed as smoke
from app.config import AppSettings
from app.main import create_app
from fastapi.testclient import TestClient
from ringsentinel.config import Settings
from ringsentinel.snapshots.export import export_snapshots
from s04_bundle import write_stage03_outputs

API, WEB = "http://api.test", "https://web.test"
TOKEN = "t" * 24
SCRIPT = "/_next/static/chunks/app.js"


@pytest.fixture(autouse=True)
def isolate_analyst_token(monkeypatch):
    """Keep smoke tests independent of credentials loaded from the project .env."""
    monkeypatch.delenv("RS_ANALYST_TOKEN", raising=False)


@pytest.fixture(scope="module")
def snapshot_dir(tmp_path_factory):
    root = tmp_path_factory.mktemp("smoke")
    s = Settings(data_dir=root / "data")
    write_stage03_outputs(s)
    return export_snapshots(s, root / "snap", git_commit="deadbeef", frozen=True).directory


def build_client(snapshot_dir, tmp_path, **overrides):
    values = {
        "snapshot_dir": snapshot_dir, "analyst_token": TOKEN,
        "audit_db_url": f"sqlite:///{(tmp_path / 'audit.sqlite3').as_posix()}",
        "rate_limit_read_per_min": 0, "rate_limit_write_per_min": 0,
        "cors_origins": (WEB,), "docs_enabled": False,
    }  # fmt: skip
    values.update(overrides)
    return TestClient(create_app(AppSettings(**values)))


def web_files(snapshot_dir, *, bundle_id=None, baked_api=API, tamper=None):
    files = {}
    html = f'<html><title>RingSentinel</title><script src="{SCRIPT}"></script></html>'
    for page in smoke.PAGES:
        files[page] = (200, "text/html", html.encode())
    for name in smoke.SNAPSHOT_FILES:
        raw = (snapshot_dir / name).read_bytes()
        if bundle_id and name == "meta.json":
            doc = json.loads(raw)
            doc["bundle_id"] = bundle_id
            raw = json.dumps(doc).encode()
        if tamper == name:
            raw = raw.replace(b"{", b'{"extra": 1,', 1)
        files[f"/snapshots/{name}"] = (200, "application/json", raw)
    files["/demo-snapshots/queue.json"] = (200, "application/json", b"{}")
    files[SCRIPT] = (200, "text/javascript", f'fetch("{baked_api}/api/v1")'.encode())
    return files


def make_fetch(client, files):
    def fetch(method, url, headers=None, body=None, timeout=30.0):
        if url.startswith(API):
            r = client.request(method, url[len(API) :], headers=headers, content=body)
            return r.status_code, {k.lower(): v for k, v in r.headers.items()}, r.content
        if url.startswith(WEB):
            status, ctype, raw = files.get(url[len(WEB) :], (404, "text/plain", b"not found"))
            return status, {"content-type": ctype}, raw
        raise OSError("no route to host")

    return fetch


def run(fetch, *extra, capsys):
    code = smoke.main(["--api", API, "--web", WEB, "--wait", "0", *extra], fetch=fetch)
    return code, capsys.readouterr().out


def failures(out):
    return [line for line in out.splitlines() if line.startswith("FAIL")]


def test_a_healthy_deployment_passes(snapshot_dir, tmp_path, capsys):
    client = build_client(snapshot_dir, tmp_path)
    code, out = run(make_fetch(client, web_files(snapshot_dir)), "--expect-docs-off", capsys=capsys)
    assert code == 0 and failures(out) == [], out
    assert "frontend build points at this API" in out and "SMOKE:" in out
    assert "WARN  audit persistence" in out  # SQLite behind a public host is flagged


def test_expecting_postgres_fails_on_a_sqlite_backend(snapshot_dir, tmp_path, capsys):
    client = build_client(snapshot_dir, tmp_path)
    code, out = run(make_fetch(client, web_files(snapshot_dir)), "--expect-postgres", capsys=capsys)
    assert code == 1 and any("audit log is on Postgres" in f for f in failures(out))


def test_docs_left_on_fail_when_they_should_be_off(snapshot_dir, tmp_path, capsys):
    client = build_client(snapshot_dir, tmp_path, docs_enabled=True)
    code, out = run(make_fetch(client, web_files(snapshot_dir)), "--expect-docs-off", capsys=capsys)
    assert code == 1 and any("interactive docs are off" in f for f in failures(out))


def test_a_cors_list_without_the_frontend_origin_fails(snapshot_dir, tmp_path, capsys):
    client = build_client(snapshot_dir, tmp_path, cors_origins=("https://other.test",))
    code, out = run(make_fetch(client, web_files(snapshot_dir)), capsys=capsys)
    assert code == 1 and any("CORS allows the frontend origin" in f for f in failures(out))
    assert "RS_CORS_ORIGINS" in out  # the hint is shown on failure


def test_a_stale_frontend_snapshot_fails_with_a_fix_hint(snapshot_dir, tmp_path, capsys):
    client = build_client(snapshot_dir, tmp_path)
    files = web_files(snapshot_dir, bundle_id="0" * 64)
    code, out = run(make_fetch(client, files), capsys=capsys)
    assert code == 1
    assert any("frontend snapshot matches the API bundle" in f for f in failures(out))
    assert "sync_frontend_snapshots" in out


def test_an_edited_snapshot_file_fails_the_hash_check(snapshot_dir, tmp_path, capsys):
    client = build_client(snapshot_dir, tmp_path)
    files = web_files(snapshot_dir, tamper="queue.json")
    code, out = run(make_fetch(client, files), capsys=capsys)
    assert code == 1
    assert any("match the hashes in meta.json" in f and "queue.json" in f for f in failures(out))


def test_a_frontend_built_for_another_api_fails(snapshot_dir, tmp_path, capsys):
    client = build_client(snapshot_dir, tmp_path)
    files = web_files(snapshot_dir, baked_api="http://somewhere-else.test")
    code, out = run(make_fetch(client, files), capsys=capsys)
    assert code == 1 and any("frontend build points at this API" in f for f in failures(out))


def test_a_missing_page_fails(snapshot_dir, tmp_path, capsys):
    client = build_client(snapshot_dir, tmp_path)
    files = web_files(snapshot_dir)
    del files["/metrics/"]
    code, out = run(make_fetch(client, files), capsys=capsys)
    assert code == 1 and any("page /metrics/" in f for f in failures(out))


def test_an_unreachable_api_fails_without_hanging(snapshot_dir, capsys):
    def dead(method, url, headers=None, body=None, timeout=30.0):
        raise OSError("connection refused")

    code, out = run(dead, capsys=capsys)
    assert code == 1 and "gave up" in out and "connection refused" in out


def test_a_slow_wake_up_is_waited_for_and_noted():
    calls = {"n": 0}
    clock = {"t": 0.0}

    def fetch(method, url, headers=None, body=None, timeout=30.0):
        calls["n"] += 1
        return (503, {}, b"") if calls["n"] < 4 else (200, {}, b'{"status":"ok"}')

    checker = smoke.Checker(
        fetch, clock=lambda: clock["t"], sleep=lambda s: clock.__setitem__("t", clock["t"] + 10)
    )
    assert checker.wait_until_live(API, 120) is True
    names = {r.name: r.status for r in checker.results}
    assert names["api answers /live"] == "PASS" and names["cold start"] == "WARN"


def test_the_token_is_never_printed_and_the_audit_list_is_checked(snapshot_dir, tmp_path, capsys):
    client = build_client(snapshot_dir, tmp_path)
    code, out = run(make_fetch(client, web_files(snapshot_dir)), "--token", TOKEN, capsys=capsys)
    assert code == 0 and TOKEN not in out
    assert "PASS  audit list with the token works" in out


def test_a_wrong_token_fails_the_audit_list_check(snapshot_dir, tmp_path, capsys):
    client = build_client(snapshot_dir, tmp_path)
    code, out = run(make_fetch(client, web_files(snapshot_dir)), "--token", "w" * 24, capsys=capsys)
    assert code == 1 and any("audit list with the token works" in f for f in failures(out))


def test_write_check_holds_one_ring_and_proves_the_replay_is_safe(snapshot_dir, tmp_path, capsys):
    client = build_client(snapshot_dir, tmp_path)
    fetch = make_fetch(client, web_files(snapshot_dir))
    code, out = run(fetch, "--token", TOKEN, "--write-check", capsys=capsys)
    assert code == 0, out
    assert "PASS  write: first request is 201" in out
    assert "PASS  write: repeat is a safe replay" in out
    assert client.app.state.audit.count() == 1
    held = [r for r, s in client.app.state.audit.statuses().items() if s == "held"]
    assert len(held) == 1


def test_write_check_is_not_run_unless_asked(snapshot_dir, tmp_path, capsys):
    client = build_client(snapshot_dir, tmp_path)
    run(make_fetch(client, web_files(snapshot_dir)), "--token", TOKEN, capsys=capsys)
    assert client.app.state.audit.count() == 0


def test_write_check_without_a_token_is_skipped(snapshot_dir, tmp_path, capsys):
    client = build_client(snapshot_dir, tmp_path)
    code, out = run(make_fetch(client, web_files(snapshot_dir)), "--write-check", capsys=capsys)
    assert code == 0 and "SKIP  write check" in out and client.app.state.audit.count() == 0


def test_a_server_without_a_token_is_reported_read_only_not_failed(snapshot_dir, tmp_path, capsys):
    client = build_client(snapshot_dir, tmp_path, analyst_token=None)
    code, out = run(make_fetch(client, web_files(snapshot_dir)), capsys=capsys)
    assert code == 0 and "WARN  actions without a token" in out


def test_arguments_are_validated():
    with pytest.raises(SystemExit):
        smoke.main([])
    with pytest.raises(SystemExit):
        smoke.main(["--api", "ftp://x"])


def test_summarize_counts_each_status():
    rows = [smoke.Result("a", "PASS"), smoke.Result("b", "FAIL"), smoke.Result("c", "WARN"),
            smoke.Result("d", "SKIP"), smoke.Result("e", "PASS")]  # fmt: skip
    assert smoke.summarize(rows) == (2, 1, 1, 1)
