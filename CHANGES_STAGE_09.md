# CHANGES_STAGE_09

Stage 09 (M9, release v1.0.0). Unzip over your repository root; same relative paths. Only new and changed files are included.

## ADDED

- `.github/workflows/smoke.yml`
- `RELEASE_NOTES_v1.0.0.md`
- `backend/app/audit_pg.py`
- `backend/tests/test_stage09_api.py`
- `backend/tests/test_stage09_audit_pg.py`
- `backend/tests/test_stage09_deploy.py`
- `backend/tests/test_stage09_readme_sync.py`
- `backend/tests/test_stage09_smoke.py`
- `docs/DEPLOYMENT.md`
- `docs/DIAGRAM_SPECS.md`
- `docs/STAGE_09.md`
- `docs/screenshots/real-audit.png`, `real-case-graph.png`, `real-case-model-written.png`, `real-drift.png`, `real-metrics.png`, `real-queue.png`, `real-replay.png`
- `frontend/vercel.json`
- `render.yaml`
- `requirements-api.txt`
- `scripts/smoke_deployed.py`
- `scripts/sync_readme_results.py`
- `CHANGES_STAGE_09.md`

## MODIFIED

- `.env.example`
- `.github/workflows/ci.yml`
- `CHANGELOG.md`
- `HANDOVER.md`
- `README.md`
- `backend/app/audit.py`
- `backend/app/config.py`
- `backend/app/main.py`
- `backend/app/routes.py`
- `docs/ARCHITECTURE.md`
- `docs/DATA.md`
- `docs/EVALUATION.md`
- `docs/PROJECT_EXPLAINER.md`
- `frontend/.gitignore` (no longer ignores `frontend/public/snapshots`)
- `frontend/src/components/CaseView.tsx`
- `frontend/tests/ai_card.test.tsx`
- `requirements.txt` (adds `psycopg[binary]==3.3.9`)
- `scripts/reproduce.py` (calls the README sync at the end)

## DELETE (manual)

None.

## Not in the zip, but you must commit them

`data/snapshots/*.json` and `frontend/public/snapshots/*.json` already exist on your machine (they came from your Stage 08 zip, unchanged, and the build environment checked they are the same bundle). They were untracked; the `frontend/.gitignore` change lets git see the second folder. After freezing (see `docs/DEPLOYMENT.md`) re-export and commit both.

## Never in the zip

`.env`, `data/audit`, `data/raw`, `data/processed`, `.git`, `node_modules`, `.next`, `out`.
