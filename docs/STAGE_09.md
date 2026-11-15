# Stage 09: deploy, final docs, diagram specs, demo (M9)

Tag: v1.0.0 (after you run the tests, deploy, and run the smoke test). Branch: `stage-09-release`. Built on your merged Stage 08 repository.

## What was built

| Item | Where |
| --- | --- |
| Postgres audit store (same hash chain, advisory lock, per-operation connections, `AuditUnavailable`) | `backend/app/audit_pg.py`, `backend/app/audit.py` |
| Liveness route that never touches the database; `audit_backend` in health; 503 + `Retry-After` when the audit store is unreachable | `backend/app/routes.py`, `backend/app/main.py` |
| Settings accept a Postgres URL and validate the scheme without echoing it | `backend/app/config.py` |
| Honest AI label: cached output from the offline stand-in provider is no longer shown as "Written by a language model (cached)" | `frontend/src/components/CaseView.tsx`, `frontend/tests/ai_card.test.tsx` |
| Deployment: Render Blueprint, slim runtime requirements, Vercel headers | `render.yaml`, `requirements-api.txt`, `frontend/vercel.json`, `requirements.txt` |
| Deployed-site smoke test (about 45 checks) | `scripts/smoke_deployed.py`, `.github/workflows/smoke.yml` |
| README results tables generated from the results files | `scripts/sync_readme_results.py`, called by `scripts/reproduce.py` |
| CI job with a real Postgres | `.github/workflows/ci.yml` |
| Frontend snapshot folder is now committed | `frontend/.gitignore` |
| Docs | `README.md` (complete), `docs/DEPLOYMENT.md`, `docs/DIAGRAM_SPECS.md`, `docs/DEMO_SCRIPT.md`, `docs/EVALUATION.md`, `docs/ARCHITECTURE.md`, `docs/PROJECT_EXPLAINER.md`, `RELEASE_NOTES_v1.0.0.md`, `HANDOVER.md`, `CHANGELOG.md`, five new screenshots of the real bundle and two of case pages |

## Decisions and deviations (flagged, not silent)

1. **Postgres instead of SQLite on the host.** Render's free disk is erased on every restart, which would silently reset the audit chain. This is a scope addition to the plan's "free Postgres (Neon or Supabase)" line, which the plan already lists; the SQLite store remains the default for local use.
2. **Frontend snapshots are committed.** `frontend/.gitignore` used to ignore `frontend/public/snapshots` until the numbers were frozen. A deployed site needs them for the sleeping-API fallback, so the rule was removed; re-sync and commit them whenever the bundle changes.
3. **The builder did not freeze the evaluation.** That is a promise about your numbers, so it is yours: `python scripts\export_snapshots.py --frozen --git-commit <sha>`.
4. **A misleading label was corrected.** In the real bundle 99 of 100 model-style case files came from the offline stand-in but were captioned "Written by a language model (cached)". They are now captioned "Offline stand-in, not a language model".
5. **`RS_TRUSTED_PROXY_HOPS=2` is an inference** (see `docs/DEPLOYMENT.md`); verify it on first deploy.
6. **README screenshots show the unfrozen banner.** Retake them after freezing if you want them clean.
7. **Licences.** IBM data is reported as CDLA-Sharing-1.0 and the repository commits a derived bundle: confirm before making the repository public. Elliptic is CC BY-NC-ND 4.0: nothing derived from it is committed except the results table.
8. **Not built, by choice:** a custom domain, monitoring, database backups, a deployment pipeline of our own, individual analyst accounts, and a Razorpay webhook feed (cut in Stage 08).

## How to run (Windows cmd, repo root, venv active)

```
pip install -r requirements.txt
pytest
ruff check .
python scripts\check_docs.py
python scripts\sync_readme_results.py --check
cd frontend
npm ci
npm run check
npm run build
cd ..
```

Postgres tests: create an empty database whose name contains `test`, then `set RS_TEST_POSTGRES_URL=postgresql://USER:PASSWORD@localhost:5432/ringsentinel_test` and run `pytest backend\tests\test_stage09_audit_pg.py -rs`; without the variable those 12 tests skip. Deploy: `docs/DEPLOYMENT.md`. Check a deployed site: `python scripts\smoke_deployed.py --api https://<api> --web https://<site> --expect-postgres --expect-docs-off --wait 120`.

## Test status

Backend with `RS_TEST_POSTGRES_URL` set to a local Postgres 16: 733 passed, 8 skipped. Backend without it: 721 passed, 20 skipped (the 12 Postgres tests, plus the real-data and PyTorch tests that need files or an optional package). Frontend: 122 passed. `ruff check .` clean; `scripts/check_docs.py` OK; `scripts/secrets_scan.py` found nothing. All run in the builder's Linux sandbox, not on your Windows machine: run them and compare. `scripts/smoke_deployed.py` was also run live against the real bundle (API from `requirements-api.txt`, local Postgres 16, built static site): 44 passed, 0 failed, 1 warning (not frozen), including the opt-in write check.

## Known limits

See README "Limitations" and `docs/PROJECT_EXPLAINER.md` section 10. In short: nothing was run on the real hosts; synthetic data, one seed, no intervals; placeholder FX; uncalibrated queue score; 1 of 500 case files from a real model; feedback rule unvalidated; hash chain detects but does not prevent edits; one shared token.
