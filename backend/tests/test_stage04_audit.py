"""Hash-chained audit log (D13): chain, tamper detection, transitions, idempotency, threads."""

import sqlite3
import threading

import pytest
from app.audit import (
    GENESIS_HASH,
    AuditLog,
    IdempotencyConflict,
    InvalidTransition,
    allowed_actions,
    entry_hash,
    request_digest,
    sqlite_path_from_url,
)

R1, R2 = "R-" + "a" * 12, "R-" + "b" * 12


def key(n):
    return f"key-{n:016d}"


@pytest.fixture
def log():
    audit = AuditLog("sqlite:///:memory:")
    yield audit
    audit.close()


def test_empty_log_verifies_with_the_genesis_head(log):
    out = log.verify()
    assert out == {
        "ok": True, "entries": 0, "head_hash": GENESIS_HASH, "first_bad_seq": None, "reason": None,
    }  # fmt: skip


def test_entries_are_chained_from_the_genesis_hash(log):
    first = log.append(R1, "hold", "asha", "wait", key(1)).entry
    second = log.append(R2, "confirm", "ravi", "", key(2)).entry
    assert (first["seq"], second["seq"]) == (1, 2)
    assert first["prev_hash"] == GENESIS_HASH and second["prev_hash"] == first["hash"]
    assert first["hash"] == entry_hash(first) != second["hash"]
    out = log.verify()
    assert out["ok"] and out["entries"] == 2 and out["head_hash"] == second["hash"]


def test_hash_changes_with_every_hashed_field():
    base = {
        "seq": 1, "ts": "t", "ring_id": R1, "action": "hold", "analyst": "a", "note": "n",
        "idempotency_key": key(1), "request_sha256": "x", "prev_hash": GENESIS_HASH,
    }  # fmt: skip
    seen = {entry_hash(base)}
    for field, other in (("seq", 2), ("ts", "u"), ("ring_id", R2), ("action", "confirm"),
                         ("analyst", "b"), ("note", "m"), ("idempotency_key", key(2)),
                         ("request_sha256", "y"), ("prev_hash", "1" * 64)):  # fmt: skip
        changed = dict(base, **{field: other})
        assert entry_hash(changed) not in seen, field
        seen.add(entry_hash(changed))
    assert request_digest(R1, "hold", "a", "n") != request_digest(R1, "hold", "a", "m")


def _tamper(log, sql, args=()):
    log._db.execute(sql, args)


def _filled(log):
    log.append(R1, "hold", "asha", "first", key(1))
    log.append(R2, "dismiss", "ravi", "second", key(2))
    log.append(R1, "confirm", "asha", "third", key(3))


def test_editing_a_note_breaks_verification_at_that_entry(log):
    _filled(log)
    _tamper(log, "UPDATE audit SET note = 'edited' WHERE seq = 2")
    out = log.verify()
    assert out["ok"] is False and out["first_bad_seq"] == 2 and out["head_hash"] is None
    assert "request digest" in out["reason"]


def test_editing_the_action_and_recomputing_only_that_hash_breaks_the_next_link(log):
    _filled(log)
    row = dict(log._db.execute("SELECT * FROM audit WHERE seq = 2").fetchone())
    row["action"] = "confirm"
    row["request_sha256"] = request_digest(R2, "confirm", row["analyst"], row["note"])
    new_hash = entry_hash(row)  # a careful forger fixes entry 2 completely...
    _tamper(log, "UPDATE audit SET action='confirm', request_sha256=?, hash=? WHERE seq=2",
            (row["request_sha256"], new_hash))  # fmt: skip
    out = log.verify()
    # ...but entry 3 still points at the old hash of entry 2
    assert out["ok"] is False and out["first_bad_seq"] == 3
    assert "prev_hash" in out["reason"]


def test_overwriting_a_hash_is_detected(log):
    _filled(log)
    _tamper(log, "UPDATE audit SET hash = ? WHERE seq = 1", ("f" * 64,))
    out = log.verify()
    assert out["ok"] is False and out["first_bad_seq"] in (1, 2)


def test_deleting_a_middle_entry_is_detected(log):
    _filled(log)
    _tamper(log, "DELETE FROM audit WHERE seq = 2")
    out = log.verify()
    assert out["ok"] is False and out["first_bad_seq"] == 3 and "gap" in out["reason"]


def test_deleting_the_first_entry_is_detected(log):
    _filled(log)
    _tamper(log, "DELETE FROM audit WHERE seq = 1")
    out = log.verify()
    assert out["ok"] is False and out["first_bad_seq"] == 2


def test_truncating_the_tail_is_not_detectable_but_the_head_hash_changes(log):
    _filled(log)
    head = log.verify()["head_hash"]
    _tamper(log, "DELETE FROM audit WHERE seq = 3")
    out = log.verify()
    assert out["ok"] is True and out["head_hash"] != head  # why callers should record the head


def test_status_follows_the_latest_action(log):
    assert log.status_of(R1) == "pending" and log.statuses() == {}
    log.append(R1, "hold", "a", "", key(1))
    assert log.status_of(R1) == "held"
    log.append(R2, "dismiss", "a", "", key(2))
    log.append(R1, "confirm", "a", "", key(3))
    assert log.statuses() == {R1: "confirmed", R2: "dismissed"}
    assert log.n_actions(R1) == 2 and log.count() == 3


def test_transition_rules():
    assert allowed_actions("pending") == ("confirm", "dismiss", "hold")
    assert allowed_actions("held") == ("confirm", "dismiss")
    assert allowed_actions("confirmed") == () and allowed_actions("dismissed") == ()


@pytest.mark.parametrize("first", ["confirm", "dismiss"])
def test_a_decided_ring_is_closed(log, first):
    log.append(R1, first, "a", "", key(1))
    for n, action in enumerate(("confirm", "dismiss", "hold"), start=2):
        with pytest.raises(InvalidTransition):
            log.append(R1, action, "a", "", key(n))
    assert log.count() == 1 and log.verify()["ok"]


def test_holding_twice_is_refused_but_hold_then_decide_works(log):
    log.append(R1, "hold", "a", "", key(1))
    with pytest.raises(InvalidTransition):
        log.append(R1, "hold", "a", "", key(2))
    log.append(R1, "dismiss", "a", "", key(3))
    assert log.status_of(R1) == "dismissed"


def test_unknown_action_is_rejected_before_touching_the_log(log):
    with pytest.raises(ValueError):
        log.append(R1, "delete", "a", "", key(1))
    assert log.count() == 0


def test_same_key_same_request_replays_the_stored_entry(log):
    first = log.append(R1, "hold", "a", "n", key(1))
    again = log.append(R1, "hold", "a", "n", key(1))
    assert first.replayed is False and again.replayed is True
    assert again.entry["hash"] == first.entry["hash"] and log.count() == 1


def test_same_key_different_request_is_a_conflict(log):
    log.append(R1, "hold", "a", "n", key(1))
    for args in ((R1, "confirm", "a", "n"), (R1, "hold", "b", "n"), (R1, "hold", "a", "x"),
                 (R2, "hold", "a", "n")):  # fmt: skip
        with pytest.raises(IdempotencyConflict):
            log.append(*args, key(1))
    assert log.count() == 1


def test_a_failed_append_leaves_no_partial_state_and_the_next_one_works(log):
    log.append(R1, "confirm", "a", "", key(1))
    with pytest.raises(InvalidTransition):
        log.append(R1, "hold", "a", "", key(2))
    log.append(R2, "hold", "a", "", key(3))
    assert [e["seq"] for e in log.entries()] == [2, 1] and log.verify()["ok"]


def test_concurrent_identical_requests_write_exactly_one_entry(log):
    results, errors = [], []

    def worker():
        try:
            results.append(log.append(R1, "confirm", "a", "n", key(7)))
        except Exception as exc:  # pragma: no cover - would fail the assert below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and log.count() == 1
    assert sum(1 for r in results if not r.replayed) == 1 and log.verify()["ok"]


def test_concurrent_different_requests_keep_the_chain_intact(log):
    def worker(n):
        log.append(f"R-{n:012x}", "hold", "a", "", key(n))

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    out = log.verify()
    assert out["ok"] and out["entries"] == 20


def test_the_log_persists_in_a_file_and_the_chain_continues_after_reopening(tmp_path):
    url = f"sqlite:///{(tmp_path / 'sub' / 'audit.sqlite3').as_posix()}"
    one = AuditLog(url)
    head = one.append(R1, "hold", "a", "", key(1)).entry["hash"]
    one.close()
    two = AuditLog(url)
    nxt = two.append(R1, "confirm", "a", "", key(2)).entry
    assert nxt["prev_hash"] == head and nxt["seq"] == 2 and two.verify()["ok"]
    two.close()


def test_tampering_with_the_file_from_outside_is_caught_on_reopen(tmp_path):
    path = tmp_path / "audit.sqlite3"
    log = AuditLog(f"sqlite:///{path.as_posix()}")
    log.append(R1, "hold", "a", "secret", key(1))
    log.close()
    raw = sqlite3.connect(path)
    raw.execute("UPDATE audit SET analyst = 'someone-else'")
    raw.commit()
    raw.close()
    reopened = AuditLog(f"sqlite:///{path.as_posix()}")
    assert reopened.verify()["ok"] is False
    reopened.close()


@pytest.mark.parametrize("bad", ["postgres://u@h/db", "sqlite://", "sqlite:///", "", "file.db"])
def test_unsupported_database_urls_are_refused_with_a_clear_message(bad):
    with pytest.raises(ValueError, match="RS_AUDIT_DB_URL"):
        sqlite_path_from_url(bad)


def test_sqlite_url_forms():
    assert sqlite_path_from_url("sqlite:///:memory:") == ":memory:"
    assert sqlite_path_from_url("sqlite:///data/audit.db") == "data/audit.db"
    assert sqlite_path_from_url("sqlite:////abs/audit.db") == "/abs/audit.db"
    assert sqlite_path_from_url("sqlite:///C:/Users/me/audit.db") == "C:/Users/me/audit.db"
