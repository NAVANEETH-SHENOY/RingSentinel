"""Hash-chained, append-only analyst action log (data stage D13, component C12).

Every entry stores the SHA-256 of its own canonical content, which includes the hash of the
entry before it, so changing, deleting or reordering any earlier entry breaks verification from
that point on. This DETECTS tampering; it does not prevent it, and it cannot see entries removed
from the very end of the log unless the head hash was recorded elsewhere (verify returns it).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

GENESIS_HASH = "0" * 64
ACTIONS = ("confirm", "dismiss", "hold")
STATUS_OF = {"confirm": "confirmed", "dismiss": "dismissed", "hold": "held"}
_FIELDS = (
    "seq", "ts", "ring_id", "action", "analyst", "note", "idempotency_key", "request_sha256",
    "prev_hash",
)  # fmt: skip

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    seq INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    ring_id TEXT NOT NULL,
    action TEXT NOT NULL,
    analyst TEXT NOT NULL,
    note TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_sha256 TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
)
"""


class AuditError(Exception):
    """Base class for audit-log refusals."""


class IdempotencyConflict(AuditError):
    """The same idempotency key was reused for a different request."""


class InvalidTransition(AuditError):
    """The ring's current status does not allow this action."""


@dataclass(frozen=True)
class AppendResult:
    entry: dict
    replayed: bool


def request_digest(ring_id: str, action: str, analyst: str, note: str) -> str:
    text = json.dumps([ring_id, action, analyst, note], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def entry_hash(entry: dict) -> str:
    """SHA-256 over the canonical JSON of the hashed fields (everything except `hash`)."""
    body = {k: entry[k] for k in _FIELDS}
    text = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def allowed_actions(status: str) -> tuple[str, ...]:
    """Transition rules: pending -> any; held -> confirm or dismiss; decided rings are closed."""
    if status == "pending":
        return ACTIONS
    if status == "held":
        return ("confirm", "dismiss")
    return ()


def sqlite_path_from_url(url: str) -> str:
    """Accept sqlite:///relative-or-absolute/path and sqlite:///:memory:. Nothing else yet."""
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise ValueError(
            "RS_AUDIT_DB_URL must look like sqlite:///path/to/file.sqlite3 (Postgres support "
            "is planned for the deployment stage)"
        )
    path = url[len(prefix):]
    if not path:
        raise ValueError("RS_AUDIT_DB_URL has no database path")
    return path


class AuditLog:
    def __init__(self, url: str):
        path = sqlite_path_from_url(url)
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    # ------------------------------------------------------------------ reads
    def _rows(self, sql: str, args: tuple = ()) -> list[dict]:
        return [dict(r) for r in self._db.execute(sql, args).fetchall()]

    def entries(self, limit: int = 100, offset: int = 0) -> list[dict]:
        with self._lock:
            return self._rows(
                "SELECT * FROM audit ORDER BY seq DESC LIMIT ? OFFSET ?", (limit, offset)
            )

    def count(self) -> int:
        with self._lock:
            return int(self._db.execute("SELECT COUNT(*) FROM audit").fetchone()[0])

    def statuses(self) -> dict[str, str]:
        """Latest status per ring that has at least one action (others are 'pending')."""
        with self._lock:
            rows = self._rows(
                "SELECT ring_id, action FROM audit WHERE seq IN "
                "(SELECT MAX(seq) FROM audit GROUP BY ring_id)"
            )
        return {r["ring_id"]: STATUS_OF[r["action"]] for r in rows}

    def status_of(self, ring_id: str) -> str:
        with self._lock:
            return self._status_locked(ring_id)

    def _status_locked(self, ring_id: str) -> str:
        row = self._db.execute(
            "SELECT action FROM audit WHERE ring_id = ? ORDER BY seq DESC LIMIT 1", (ring_id,)
        ).fetchone()
        return STATUS_OF[row["action"]] if row else "pending"

    def n_actions(self, ring_id: str) -> int:
        with self._lock:
            row = self._db.execute("SELECT COUNT(*) FROM audit WHERE ring_id = ?", (ring_id,))
            return int(row.fetchone()[0])

    # ----------------------------------------------------------------- append
    def append(
        self, ring_id: str, action: str, analyst: str, note: str, idempotency_key: str
    ) -> AppendResult:
        """Append one entry, or return the stored one if this exact request was already made."""
        if action not in ACTIONS:
            raise ValueError(f"unknown action {action!r}")
        digest = request_digest(ring_id, action, analyst, note)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                existing = self._db.execute(
                    "SELECT * FROM audit WHERE idempotency_key = ?", (idempotency_key,)
                ).fetchone()
                if existing is not None:
                    if existing["request_sha256"] != digest:
                        raise IdempotencyConflict(
                            "idempotency key already used for another request"
                        )
                    self._db.execute("COMMIT")
                    return AppendResult(dict(existing), replayed=True)
                status = self._status_locked(ring_id)
                if action not in allowed_actions(status):
                    raise InvalidTransition(f"ring is {status}; {action} is not allowed")
                last = self._db.execute(
                    "SELECT seq, hash FROM audit ORDER BY seq DESC LIMIT 1"
                ).fetchone()
                entry = {
                    "seq": (last["seq"] + 1) if last else 1,
                    "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                    "ring_id": ring_id, "action": action, "analyst": analyst, "note": note,
                    "idempotency_key": idempotency_key, "request_sha256": digest,
                    "prev_hash": last["hash"] if last else GENESIS_HASH,
                }  # fmt: skip
                entry["hash"] = entry_hash(entry)
                self._db.execute(
                    "INSERT INTO audit (seq, ts, ring_id, action, analyst, note, idempotency_key,"
                    " request_sha256, prev_hash, hash) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    tuple(entry[k] for k in (*_FIELDS, "hash")),
                )
                self._db.execute("COMMIT")
            except BaseException:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        return AppendResult(entry, replayed=False)

    # ----------------------------------------------------------------- verify
    def verify(self) -> dict:
        """Walk the whole chain. Returns ok, entry count, head hash and the first problem."""
        with self._lock:
            rows = self._rows("SELECT * FROM audit ORDER BY seq ASC")
        prev_hash, expected_seq = GENESIS_HASH, 1
        for row in rows:
            problem = None
            if row["seq"] != expected_seq:
                problem = f"sequence gap: expected {expected_seq}, found {row['seq']}"
            elif row["prev_hash"] != prev_hash:
                problem = "prev_hash does not match the previous entry"
            elif row["request_sha256"] != request_digest(
                row["ring_id"], row["action"], row["analyst"], row["note"]
            ):
                problem = "request digest does not match the stored fields"
            elif entry_hash(row) != row["hash"]:
                problem = "entry hash does not match its content"
            if problem:
                return {
                    "ok": False, "entries": len(rows), "head_hash": None,
                    "first_bad_seq": row["seq"], "reason": problem,
                }  # fmt: skip
            prev_hash, expected_seq = row["hash"], expected_seq + 1
        return {
            "ok": True, "entries": len(rows), "head_hash": prev_hash,
            "first_bad_seq": None, "reason": None,
        }  # fmt: skip
