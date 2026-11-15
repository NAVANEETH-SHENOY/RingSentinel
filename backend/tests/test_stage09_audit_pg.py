"""Postgres audit log (D13, deployed form): same behaviour as the SQLite log, plus the failure modes
that only a hosted database has.

Tests marked `needs_pg` run only when RS_TEST_POSTGRES_URL points at a DISPOSABLE Postgres whose
database name contains "test" (the fixture drops the `audit` table). In CI a Postgres service
container provides it (.github/workflows/ci.yml). The rest run everywhere.
"""

import os
import threading

import pytest
from app.audit import (
    GENESIS_HASH,
    AuditLog,
    AuditUnavailable,
    IdempotencyConflict,
    InvalidTransition,
    backend_of,
    entry_hash,
    open_audit_log,
    request_digest,
    verify_rows,
)
from app.config import AppSettings

R1, R2 = "R-" + "a" * 12, "R-" + "b" * 12
PG_URL = os.environ.get("RS_TEST_POSTGRES_URL", "").strip()
needs_pg = pytest.mark.skipif(not PG_URL, reason="RS_TEST_POSTGRES_URL is not set")


def key(n):
    return f"key-{n:016d}"


# ---------------------------------------------------------------- no server needed
@pytest.mark.parametrize(
    ("url", "kind"),
    [
        ("sqlite:///:memory:", "sqlite"),
        ("sqlite:///data/audit.db", "sqlite"),
        ("postgresql://u:p@host/db", "postgres"),
        ("postgres://u:p@host/db?sslmode=require", "postgres"),
    ],
)
def test_backend_is_chosen_from_the_url_scheme(url, kind):
    assert backend_of(url) == kind


@pytest.mark.parametrize("bad", ["", "mysql://u:secretpw@h/db", "file.db", "sqlite://", "http://x"])
def test_unknown_schemes_are_refused_without_echoing_the_url(bad):
    with pytest.raises(ValueError, match="RS_AUDIT_DB_URL") as info:
        backend_of(bad)
    assert "secretpw" not in str(info.value)


def test_settings_accept_postgres_and_refuse_other_schemes(tmp_path):
    ok = AppSettings(snapshot_dir=tmp_path, audit_db_url="postgresql://u:p@h/db")
    assert ok.audit_db_url.startswith("postgresql://")
    with pytest.raises(ValueError, match="RS_AUDIT_DB_URL"):
        AppSettings(snapshot_dir=tmp_path, audit_db_url="mysql://u:p@h/db")


def test_factory_returns_the_sqlite_log_for_a_sqlite_url():
    log = open_audit_log("sqlite:///:memory:")
    assert isinstance(log, AuditLog) and log.backend == "sqlite"
    log.close()


def test_unreachable_database_raises_audit_unavailable_and_hides_the_password():
    pytest.importorskip("psycopg")
    with pytest.raises(AuditUnavailable) as info:
        open_audit_log("postgresql://rs:secretpw@127.0.0.1:1/none?connect_timeout=2")
    assert "secretpw" not in str(info.value) and "secretpw" not in repr(info.value)


def test_verify_rows_is_shared_and_catches_a_broken_link():
    first = {
        "seq": 1,
        "ts": "t",
        "ring_id": R1,
        "action": "hold",
        "analyst": "a",
        "note": "",
        "idempotency_key": key(1),
        "request_sha256": request_digest(R1, "hold", "a", ""),
        "prev_hash": GENESIS_HASH,
    }
    first["hash"] = entry_hash(first)
    assert verify_rows([first])["ok"] is True
    broken = dict(first, prev_hash="f" * 64)
    out = verify_rows([broken])
    assert out["ok"] is False and out["first_bad_seq"] == 1


# ---------------------------------------------------------------- a real Postgres
@pytest.fixture
def log():
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(PG_URL, autocommit=True) as conn:
        dbname = conn.execute("SELECT current_database()").fetchone()[0]
        if "test" not in dbname:
            pytest.skip(
                f"refusing to drop the audit table in database {dbname!r}: name has no 'test'"
            )
        conn.execute("DROP TABLE IF EXISTS audit")
    audit = open_audit_log(PG_URL)
    yield audit
    audit.close()


def _tamper(sql, args=()):
    import psycopg

    with psycopg.connect(PG_URL, autocommit=True) as conn:
        conn.execute(sql, args)


@needs_pg
def test_pg_empty_log_verifies_with_the_genesis_head(log):
    assert log.backend == "postgres"
    assert log.verify() == {
        "ok": True,
        "entries": 0,
        "head_hash": GENESIS_HASH,
        "first_bad_seq": None,
        "reason": None,
    }
    assert log.count() == 0 and log.statuses() == {} and log.status_of(R1) == "pending"


@needs_pg
def test_pg_entries_are_chained_and_listed_newest_first(log):
    first = log.append(R1, "hold", "asha", "wait", key(1)).entry
    second = log.append(R2, "confirm", "ravi", "", key(2)).entry
    assert (first["seq"], second["seq"]) == (1, 2)
    assert first["prev_hash"] == GENESIS_HASH and second["prev_hash"] == first["hash"]
    out = log.verify()
    assert out["ok"] and out["entries"] == 2 and out["head_hash"] == second["hash"]
    assert [e["seq"] for e in log.entries()] == [2, 1]
    assert [e["seq"] for e in log.entries(limit=1, offset=1)] == [1]
    assert log.count() == 2


@needs_pg
def test_pg_transitions_follow_the_same_rules_as_sqlite(log):
    log.append(R1, "hold", "a", "", key(1))
    assert log.status_of(R1) == "held"
    log.append(R1, "confirm", "a", "", key(2))
    assert log.status_of(R1) == "confirmed" and log.n_actions(R1) == 2
    with pytest.raises(InvalidTransition):
        log.append(R1, "dismiss", "a", "", key(3))
    assert log.statuses() == {R1: "confirmed"}
    with pytest.raises(ValueError):
        log.append(R2, "delete", "a", "", key(4))


@needs_pg
def test_pg_same_request_is_replayed_and_a_reused_key_conflicts(log):
    one = log.append(R1, "hold", "a", "n", key(1))
    again = log.append(R1, "hold", "a", "n", key(1))
    assert one.replayed is False and again.replayed is True
    assert again.entry["hash"] == one.entry["hash"] and log.count() == 1
    with pytest.raises(IdempotencyConflict):
        log.append(R1, "hold", "a", "different note", key(1))
    assert log.count() == 1


@needs_pg
def test_pg_a_refused_action_leaves_no_trace(log):
    log.append(R1, "dismiss", "a", "", key(1))
    with pytest.raises(InvalidTransition):
        log.append(R1, "confirm", "a", "", key(2))
    assert log.count() == 1 and log.verify()["ok"]


@needs_pg
@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE audit SET note = 'edited' WHERE seq = 2",
        "UPDATE audit SET hash = '" + "f" * 64 + "' WHERE seq = 1",
        "DELETE FROM audit WHERE seq = 1",
        "DELETE FROM audit WHERE seq = 2",
    ],
)
def test_pg_tampering_is_detected(log, sql):
    log.append(R1, "hold", "a", "", key(1))
    log.append(R2, "hold", "a", "", key(2))
    log.append(R1, "confirm", "a", "", key(3))
    _tamper(sql)
    out = log.verify()
    assert out["ok"] is False and out["first_bad_seq"] is not None and out["reason"]


@needs_pg
def test_pg_the_chain_continues_across_instances_like_a_restart(log):
    head = log.append(R1, "hold", "a", "", key(1)).entry["hash"]
    second = open_audit_log(PG_URL)  # a fresh process would do the same
    nxt = second.append(R1, "confirm", "a", "", key(2)).entry
    assert nxt["prev_hash"] == head and nxt["seq"] == 2 and second.verify()["ok"]


@needs_pg
def test_pg_two_instances_appending_at_once_never_fork_the_chain(log):
    other = open_audit_log(PG_URL)
    errors: list[BaseException] = []

    def worker(target, base):
        try:
            for n in range(10):
                target.append(f"R-{base + n:012x}", "hold", "a", "", key(base + n))
        except BaseException as exc:  # noqa: BLE001 - collected, asserted empty below
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(log, 100)),
        threading.Thread(target=worker, args=(other, 200)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    out = log.verify()
    assert out["ok"] and out["entries"] == 20


@needs_pg
def test_pg_store_is_reachable_through_the_api_and_health_names_the_backend(tmp_path, log):
    from app.main import create_app
    from fastapi.testclient import TestClient
    from ringsentinel.config import Settings
    from ringsentinel.snapshots.export import export_snapshots
    from s04_bundle import write_stage03_outputs

    s = Settings(data_dir=tmp_path / "data")
    write_stage03_outputs(s)
    snap = export_snapshots(s, tmp_path / "snap", git_commit="deadbeef").directory
    settings = AppSettings(
        snapshot_dir=snap,
        analyst_token="t" * 24,
        audit_db_url=PG_URL,
        rate_limit_read_per_min=0,
        rate_limit_write_per_min=0,
    )
    client = TestClient(create_app(settings))
    assert client.get("/api/v1/health").json()["audit_backend"] == "postgres"
    ring = client.get("/api/v1/queue").json()["items"][0]["ring_id"]
    body = {"action": "confirm", "analyst": "asha", "note": "", "idempotency_key": key(9)}
    headers = {"X-Analyst-Token": "t" * 24}
    made = client.post(f"/api/v1/cases/{ring}/action", json=body, headers=headers)
    assert made.status_code == 201
    again = client.post(f"/api/v1/cases/{ring}/action", json=body, headers=headers)
    assert again.status_code == 200 and again.json()["replayed"] is True
    assert client.get("/api/v1/audit/verify").json()["ok"] is True
    assert client.get("/api/v1/queue").json()["items"][0]["status"] == "confirmed"
