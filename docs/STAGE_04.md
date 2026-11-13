# Stage 04: snapshots and backend

Tag: v0.5.0 (after the owner runs the tests and, once Stage 03 has run on the real data, the exporter). Branch: `stage-04-snapshots-backend`.

## What was built

- **D12 snapshot exporter** (`backend/ringsentinel/snapshots/export.py`, command `scripts/export_snapshots.py`): turns the Stage 03 outputs into a small bundle of six JSON files in `data/snapshots/` [generated]: `meta.json` [generated], `queue.json` [generated], `cases.json` [generated], `metrics.json` [generated], `drift.json` [generated], `replay.json` [generated]. The output is deterministic: sorted keys, no timestamps, the git commit passed in. `meta.json` [generated] records the SHA-256 of every source file and every bundle file plus a `bundle_id` (hash of the file hashes).
- **Schemas** (`backend/ringsentinel/snapshots/schemas.py`): one JSON Schema per bundle file. `backend/ringsentinel/snapshots/bundle.py` (`load_bundle()`) validates the schemas, the file hashes against `meta.json` [generated], and that the queue and the cases list the same rings. The exporter re-loads what it wrote, and the API refuses to start on a bundle that fails any of these checks.
- **D13 backend** (`backend/app/`): `create_app()` in `backend/app/main.py`, routes in `backend/app/routes.py`, hash-chained audit log in `backend/app/audit.py`, rate limiter in `backend/app/ratelimit.py`, settings in `backend/app/config.py`, request models in `backend/app/schemas.py`, read-only snapshot view in `backend/app/store.py`.
- **Run command** `scripts/run_api.py`.

## The queue ranking

Each ring gets `expected_value_inr = score x capture x amount_inr - review_cost - fp_cost x n_members x (1 - score)` (computed by `expected_value_inr()`), with the cost assumptions taken from `metrics.json` [generated]. The score is an uncalibrated model output, so this is a ranking heuristic, not a forecast of rupees; the queue says so (`score_calibrated` is always false). It is not the validated net-value rule from Stage 03 (that rule uses true labels, which an analyst does not have). Rings are ordered by this value, ties by `ring_id`, and at most 500 rings are exported (`--max-rings`); `meta.json` [generated] reports how many were dropped.

A ring id is `R-` plus the first 12 hex characters of SHA-256 over the detector name and the sorted member accounts (`ring_id_for()`), so it is stable across exports.

## What is a placeholder

- `drift.json` [generated] and `replay.json` [generated] are valid but empty (`status: not_built`, built in Stage 07).
- Each case carries an `ai` block with `status: not_built` (the investigator, verifier and benign explanation arrive in Stage 06). Nothing in a case comes from a language model.
- `evaluation_frozen` in `meta.json` [generated] is false unless the exporter is run with `--frozen`. Do that only after Stage 03 has been run on the real data and its numbers are accepted.

## Endpoints (all under the prefix /api/v1)

| Method and path | Auth | What it returns |
| --- | --- | --- |
| GET /health | none | bundle id, git commit, ring count, audit entry count, whether actions are enabled |
| GET /queue?status=&limit=&offset= | none | ranked rings with their current status (pending, confirmed, dismissed, held); limit 1 to 500 |
| GET /cases/{ring_id} | none | the case (members, edges, top features, AI placeholder), status, number of actions |
| GET /metrics | none | Stage 03 metrics, cost sweep, ablations, robustness, latency, results table |
| GET /drift, GET /replay | none | the placeholder documents (Stage 07) |
| POST /cases/{ring_id}/action | X-Analyst-Token | appends a confirm, dismiss or hold entry to the audit log |
| GET /audit?limit=&offset= | X-Analyst-Token | newest entries first |
| GET /audit/verify | none | walks the whole chain: ok, entry count, head hash, first bad entry |

Interactive documentation is served at /api/docs.

## The audit log

Each entry stores the SHA-256 of its own canonical content, which includes the previous entry's hash (the first uses 64 zeros). `AuditLog.verify()` recomputes everything. Editing a field, replacing a hash, deleting a middle entry or reordering entries is detected, and the response names the first bad entry. Limits, stated plainly:

- It detects tampering; it does not prevent it. Anyone with write access to the database file can change it.
- Removing entries from the very end is not detected by the chain alone. `verify` returns the head hash; record it somewhere else if that matters.
- The analyst name is a free-text label. There is one shared token, so the log does not prove who acted.

Rules for actions (`allowed_actions()`): a pending ring accepts confirm, dismiss or hold; a held ring accepts confirm or dismiss; a confirmed or dismissed ring is closed (HTTP 409). Every action needs an `idempotency_key` (16 to 64 characters of letters, digits, underscore or hyphen). Sending the same key with the same request returns the stored entry (HTTP 200, `replayed: true`) and writes nothing; the same key with a different request is HTTP 409. The check and the insert run in one SQLite `BEGIN IMMEDIATE` transaction, and a test fires twelve simultaneous identical requests.

## Security notes

- Writes and the audit list need the header X-Analyst-Token, compared in constant time. If `RS_ANALYST_TOKEN` is not set, those endpoints answer 503 and the rest of the API still works. The token must be at least 16 characters.
- Inputs are validated by pydantic: unknown fields, control characters, over-long notes and malformed ids are rejected with 422 before anything is written. SQL parameters are always bound.
- CORS allows only the origins in `RS_CORS_ORIGINS` (no wildcard accepted), methods GET, POST and OPTIONS, and the headers Content-Type and X-Analyst-Token.
- Rate limits are per client address and per process: 120 reads and 20 writes a minute by default. Behind a proxy every request may appear to come from the proxy's address, and several worker processes each count separately; revisit this at deployment (Stage 09).
- The snapshot is public demo data, so reads are open. Do not put anything private in the bundle.

## How to run (Windows cmd, repo root, venv active, Stage 03 outputs present)

```
pip install -r requirements.txt
python scripts\export_snapshots.py
python scripts\run_api.py
```

Set `RS_ANALYST_TOKEN` in `.env` first if you want to take actions. Then open http://127.0.0.1:8000/api/docs. The audit database is created at `data\audit\audit.sqlite3` [generated] on first start; add `data/audit/` [generated] to `.gitignore`.

## Known limits

- Never run against real Stage 03 output: the builder's sandbox has none. The exporter and API were exercised on hand-made files and on the synthetic pipeline output.
- The expected-value ranking uses an uncalibrated score (see above).
- `edges` in a case are rebuilt from the up to 500 transfers listed per ring in `rings.json` [generated]; larger rings are flagged `edges_truncated`.
- Only SQLite is supported for the audit database; Postgres is a Stage 09 task (free-tier limits to be verified then).
- The threshold feedback loop from dismissals (plan section 5.9) is not built; it is Stage 07.
