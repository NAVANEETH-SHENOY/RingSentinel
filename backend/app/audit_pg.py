"""Postgres twin of the audit log (data stage D13, component C12, deployed form).

Same public methods and the same hash chain as `app.audit.AuditLog` (SQLite). Why a second
implementation: free web hosts (Render's free tier, for one) wipe the local disk on every restart
or spin-down, so a SQLite file there would lose the decision log. A hosted Postgres keeps it.

Design choices, each with its reason:
  * One short-lived connection per operation. A serverless Postgres (Neon) suspends its compute
    after a few idle minutes and drops open connections; a connection kept for hours would be dead
    on the next request. Opening one costs tens of milliseconds, which is fine at analyst volume.
  * Appends take a transaction-scoped advisory lock, so two API instances (or a restart overlapping
    a deploy) can never both read the same "last entry" and fork the chain. The primary key on
    `seq` is the backstop if the lock were ever bypassed.
  * The database URL (it carries a password) is never put in an error message or a log line.
  * `psycopg` is imported lazily, so a SQLite-only setup does not need the driver installed.
"""

from __future__ import annotations

from app.audit import (
    ACTIONS,
    STATUS_OF,
    AppendResult,
    AuditUnavailable,
    IdempotencyConflict,
    InvalidTransition,
    allowed_actions,
    next_entry,
    request_digest,
    verify_rows,
)

# Any fixed 63-bit integer; it only has to be the same in every process that writes this table.
ADVISORY_LOCK_KEY = 7_291_834_205_117
CONNECT_TIMEOUT_S = 15

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    seq BIGINT PRIMARY KEY,
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
_INDEX = "CREATE INDEX IF NOT EXISTS audit_ring_seq ON audit (ring_id, seq)"
_COLUMNS = (
    "seq",
    "ts",
    "ring_id",
    "action",
    "analyst",
    "note",
    "idempotency_key",
    "request_sha256",
    "prev_hash",
    "hash",
)


class PostgresAuditLog:
    backend = "postgres"

    def __init__(self, url: str):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise RuntimeError(
                "A postgresql:// RS_AUDIT_DB_URL needs the psycopg package "
                "(pip install -r requirements.txt)"
            ) from exc
        self._psycopg = psycopg
        self._dict_row = dict_row
        self._url = url
        with self._connect() as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (ADVISORY_LOCK_KEY,))
            conn.execute(_SCHEMA)
            conn.execute(_INDEX)

    # -------------------------------------------------------------- plumbing
    def _connect(self):
        """A new autocommit connection. Failures become AuditUnavailable without the URL."""
        try:
            return self._psycopg.connect(
                self._url,
                autocommit=True,
                row_factory=self._dict_row,
                connect_timeout=CONNECT_TIMEOUT_S,
            )
        except self._psycopg.OperationalError as exc:
            raise AuditUnavailable("the audit database cannot be reached") from exc

    def _rows(self, sql: str, args: tuple = ()) -> list[dict]:
        try:
            with self._connect() as conn:
                return [dict(r) for r in conn.execute(sql, args).fetchall()]
        except self._psycopg.OperationalError as exc:
            raise AuditUnavailable("the audit database cannot be reached") from exc

    def close(self) -> None:  # connections are per operation, so there is nothing to release
        return None

    # ------------------------------------------------------------------ reads
    def entries(self, limit: int = 100, offset: int = 0) -> list[dict]:
        return self._rows(
            "SELECT * FROM audit ORDER BY seq DESC LIMIT %s OFFSET %s", (limit, offset)
        )

    def count(self) -> int:
        return int(self._rows("SELECT COUNT(*) AS n FROM audit")[0]["n"])

    def statuses(self) -> dict[str, str]:
        """Latest status per ring that has at least one action (others are 'pending')."""
        rows = self._rows(
            "SELECT ring_id, action FROM audit WHERE seq IN "
            "(SELECT MAX(seq) FROM audit GROUP BY ring_id)"
        )
        return {r["ring_id"]: STATUS_OF[r["action"]] for r in rows}

    def status_of(self, ring_id: str) -> str:
        rows = self._rows(
            "SELECT action FROM audit WHERE ring_id = %s ORDER BY seq DESC LIMIT 1", (ring_id,)
        )
        return STATUS_OF[rows[0]["action"]] if rows else "pending"

    def n_actions(self, ring_id: str) -> int:
        rows = self._rows("SELECT COUNT(*) AS n FROM audit WHERE ring_id = %s", (ring_id,))
        return int(rows[0]["n"])

    # ----------------------------------------------------------------- append
    def append(
        self, ring_id: str, action: str, analyst: str, note: str, idempotency_key: str
    ) -> AppendResult:
        """Append one entry, or return the stored one if this exact request was already made."""
        if action not in ACTIONS:
            raise ValueError(f"unknown action {action!r}")
        digest = request_digest(ring_id, action, analyst, note)
        try:
            with self._connect() as conn, conn.transaction():
                conn.execute("SELECT pg_advisory_xact_lock(%s)", (ADVISORY_LOCK_KEY,))
                existing = conn.execute(
                    "SELECT * FROM audit WHERE idempotency_key = %s", (idempotency_key,)
                ).fetchone()
                if existing is not None:
                    if existing["request_sha256"] != digest:
                        raise IdempotencyConflict(
                            "idempotency key already used for another request"
                        )
                    return AppendResult(dict(existing), replayed=True)
                latest = conn.execute(
                    "SELECT action FROM audit WHERE ring_id = %s ORDER BY seq DESC LIMIT 1",
                    (ring_id,),
                ).fetchone()
                status = STATUS_OF[latest["action"]] if latest else "pending"
                if action not in allowed_actions(status):
                    raise InvalidTransition(f"ring is {status}; {action} is not allowed")
                last = conn.execute(
                    "SELECT seq, hash FROM audit ORDER BY seq DESC LIMIT 1"
                ).fetchone()
                entry = next_entry(last, ring_id, action, analyst, note, idempotency_key, digest)
                conn.execute(
                    "INSERT INTO audit (seq, ts, ring_id, action, analyst, note, idempotency_key,"
                    " request_sha256, prev_hash, hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    tuple(entry[k] for k in _COLUMNS),
                )
        except self._psycopg.OperationalError as exc:
            raise AuditUnavailable("the audit database cannot be reached") from exc
        return AppendResult(entry, replayed=False)

    # ----------------------------------------------------------------- verify
    def verify(self) -> dict:
        """Walk the whole chain. Returns ok, entry count, head hash and the first problem."""
        return verify_rows(self._rows("SELECT * FROM audit ORDER BY seq ASC"))
