# HANDOVER (end of Stage 05 build; read before continuing in a new chat)

## Summary

Plain language: RingSentinel will help fraud analysts find and review groups of accounts that move money like a coordinated ring, with honest measurement and a human making every decision. So far the project loads the public IBM synthetic money-laundering data, labels the known rings, splits the data by time, builds the account graph with hub control, scores every transfer with four detectors, groups flagged transfers into candidate rings and measures everything on a held-out test period including the rupee cost of false alarms (Stages 01 to 03). New in Stage 04: the results can be packaged into a small, checked bundle of JSON files, and a local server hands the ranked review queue, the case details and the metrics to a user interface, and records each analyst decision (confirm, dismiss, hold) in a log where every entry carries a fingerprint of the one before it, so edits are detectable. New in Stage 05: a web interface (`frontend/`) shows the ranked queue, a graph of each ring's transfers, the metrics and the audit log. It reads the backend when it answers and otherwise the saved bundle files, and it ships with an invented demo bundle (marked DEMO on every page) so it can be used before real results exist. It is read-only; confirm, dismiss and hold buttons come in Stage 07. **The Stage 03 measuring code has still never been run on the real data, so there are no real results; the Stage 04 bundle and the Stage 05 interface have only seen synthetic, hand-made or demo data.**

Technical: Stage 01 (D1/D2/D4 plus two baselines), Stage 02 (D3, D5, D6) and Stage 03 (D7 detectors with a `SplitVault`, D8 rings, D9 metrics, cost model, ablation, robustness, latency, `scripts/reproduce.py`) are unchanged. Stage 05 adds C15: `frontend/` (Next.js 16 static export, React 19, TypeScript, d3-force, Vitest), `scripts/make_demo_bundle.py`, `scripts/sync_frontend_snapshots.py`, `frontend/public/demo-snapshots`, `.github/workflows/frontend.yml`. Stage 04 adds D12 (`backend/ringsentinel/snapshots/`: schemas, loader, deterministic exporter, `scripts/export_snapshots.py`) and D13 (`backend/app/`: FastAPI `create_app()`, routes, SQLite hash-chained `AuditLog`, rate limiter, settings; `scripts/run_api.py`).

## Architecture and key decisions

See `docs/ARCHITECTURE.md`, `docs/STAGE_04.md`, `docs/EVALUATION.md` and the decision log in `docs/PROJECT_EXPLAINER.md`. The ones to remember:
- Terminal: Windows cmd (git commands in Git Bash). Python 3.13.3 on the owner's machine.
- Dataset: IBM AML HI-Small by default; `RS_DATASET_VARIANT` switches variant; HI-Medium never tried.
- Stage 03 protocol: fit on train; early stopping and every threshold on validation; test scored once per detector. Rupee defaults INR 250 per review, INR 500 per wrongly included account, capture 1.0 (planning assumptions, rationale in `docs/EVALUATION.md`). Stage 03 code depends only on parquet contracts and re-implements the baselines.
- Stage 04 bundle: six canonical JSON files in `data/snapshots/` [generated], schema-validated and tied together by SHA-256 hashes in `meta.json` [generated]; the API refuses to start on a bundle that fails any check. Drift, replay and the AI case block are explicit `not_built` placeholders (Stages 06 and 07).
- Queue order: `EV = score x capture x amount_inr - review - fp x n_members x (1 - score)`. The score is uncalibrated, so this is a ranking heuristic and is labelled as one in the data (`score_calibrated: false`).
- Audit log: SQLite, explicit `seq`, SHA-256 chain, idempotency keys, decided rings are closed (409), pending accepts any action, held accepts confirm or dismiss. It detects tampering but does not prevent it, and tail truncation is invisible without an outside copy of the head hash. One shared token (`RS_ANALYST_TOKEN`, at least 16 characters) gates actions and the audit list; reads are open.
- Stage 05: static export, API first then saved snapshot then demo bundle (origin always shown); case id in a query string; own SVG charts and a deterministic d3-force layout; the case graph shows at most 500 accounts, chosen by transfer volume (ties by id); metrics extractors are tolerant of layout and say "not recognised" instead of guessing; light mode only. Node 22.12 or newer is required by the pinned test tooling.
- New dependencies (pinned): `fastapi==0.162.5`, `uvicorn==0.54.0`, `jsonschema==4.26.0`, and `httpx2==2.16.0` for the tests only (Starlette reports plain httpx as deprecated for its test client).

## Milestone status

| Milestone | Stage | Status |
| --- | --- | --- |
| M0 | 00 scaffold | Done (owner: 16 passed) |
| M1 | 01 data and baselines | Done; owner ran it on the real corrected HI-Small (85 passed); tag v0.2.0 |
| M2 | 02 graph and features | Built; builder ran every step on the real files. Owner's test output and the v0.3.0 tag were not seen |
| M3 | 03 detectors and evaluation | Built and tested on synthetic data in the sandbox. The owner has not yet applied it; real-data run, merge and tag v0.4.0 pending |
| M4 | 04 snapshots and backend | Built and tested in the sandbox (see below). Owner's run, merge and tag v0.5.0 pending. Needs the real Stage 03 outputs before the bundle means anything |
| M5 | 05 frontend core | Built and tested in the sandbox (see below). Owner's run, merge and tag v0.6.0 pending |
| M6 to M9 | 06 to 09 | Not started |

## Repo structure

See the repo map in `docs/PROJECT_EXPLAINER.md`.

## Setup and run (Windows cmd, repo root)

```
py -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
pytest
ruff check .
python scripts\check_docs.py
python scripts\run_stage03.py
python scripts\reproduce.py
python scripts\export_snapshots.py
python scripts\sync_frontend_snapshots.py
python scripts\run_api.py
cd frontend
npm ci
npm run check
npm run dev
```

Raw files go in `data\raw`: HI-Small_Trans.csv and HI-Small_Patterns.txt. Run `python scripts\reproduce.py` twice; the second run should print REPRODUCED. Set `RS_ANALYST_TOKEN` in `.env` before taking actions through the API; the interactive API page is http://127.0.0.1:8000/api/docs. Add `data/audit/` [generated] to `.gitignore`.

## Environment variable names

The names are: `RS_DATASET_VARIANT`, `RS_DATA_DIR`, `RS_SEED`, `RS_TRAIN_FRAC`, `RS_VAL_FRAC`, `RS_HUB_CAP`, `RS_ATTR_CAP`, `RS_COMMUNITY_CAP`, `RS_LOUVAIN_RESOLUTION`, `RS_NEG_SAMPLE_FRAC`, `RS_REVIEW_COST_INR`, `RS_FP_COST_INR`, `RS_LOSS_CAPTURE_RATE`, `RS_RING_TAU`, `RS_RING_MIN_SIZE`, `RS_GIT_COMMIT`, `RS_SNAPSHOT_DIR`, `RS_ANALYST_TOKEN`, `RS_AUDIT_DB_URL`, `RS_CORS_ORIGINS`, `RS_RATE_LIMIT_READ_PER_MIN`, `RS_RATE_LIMIT_WRITE_PER_MIN`. Frontend (in `frontend/.env.local` [generated]): `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_API_TIMEOUT_MS`. Reserved for later: `KAGGLE_USERNAME`, `KAGGLE_KEY`, `RS_LLM_PROVIDER`, `GROQ_API_KEY`, `GEMINI_API_KEY`. The owner has Groq for development and Gemini for production, with no keys in the project yet.

## Test status (real results only)

- Owner, Windows, Python 3.13.3 (Stage 01, 12 Nov 2026): `pytest` 85 passed, ruff clean, check_docs OK. Nothing newer has been run by the owner.
- Builder, Linux sandbox (Python 3.13, pinned requirements), on a clean tree made from the Stage 02 zip plus the Stage 03 and Stage 04 zips: `pytest --ignore=backend/tests/test_stage02_pipeline.py` gave **217 passed** (117 up to Stage 03, plus 100 new Stage 04 tests: 20 exporter, 28 audit, 39 API, 8 settings and limiter, 5 integration). `ruff check .` clean with the builder's own config (rules E, F, B, UP, line length 100; the project's real ruff config was not available, so import-order rules were not checked).
- A real `uvicorn` process was started in the sandbox on a synthetic bundle; health, one hold action and audit verify returned the expected answers.
- Builder, Linux sandbox, Stage 05: `npm run check` equivalent run as three commands: `tsc --noEmit` clean, `eslint .` clean, `vitest run` **79 passed** (5 files); `npm run build` succeeded (static export, 7 routes). `backend/tests/test_stage05_bundle.py`: **9 passed**, using a two-line stub of `ringsentinel.config` because the Stage 01 to 03 sources are not in the zips. A real uvicorn process (Stage 04 code, pinned fastapi and uvicorn) served the demo bundle; the built site, driven by headless Google Chrome via Playwright, was checked against it (live statuses, audit list with the token, chain check), and with the API requests blocked (fallback to saved files). Not run: the full `pytest` of the repo.
- **NOT EXECUTED by the builder**: the Stage 01 tests and `backend/tests/test_stage02_pipeline.py` (they need Stage 01 sources and `backend/tests/conftest.py`); the real `scripts/check_docs.py` (a stand-in script found no new unresolved tokens, but it is not the real checker); the whole Stage 03 stage and the exporter on real data; CI on GitHub; Windows installs of the pinned packages (including fastapi, uvicorn, httpx2, jsonschema); the API on Windows; **for Stage 05 also**: the frontend on Windows, Node versions other than 22, browsers other than headless Chrome, the frontend CI workflow on GitHub, the real `scripts/check_docs.py` on the new docs, `python scripts\sync_frontend_snapshots.py` without `--src` (default path from settings), any real Stage 03 or exported bundle.

## Dataset citations and licence status

IBM AML (Altman et al., NeurIPS 2023 Datasets and Benchmarks): authors, title and venue confirmed on the NeurIPS proceedings page; page numbers, URL form and BibTeX not verified. Licence: the paper's supplement says "Community Data License Agreement"; the exact variant and its terms are NOT verified. Elliptic is not used yet (licence unchecked).

## Known bugs, caveats, open questions

- Everything about Stage 03 on real data is unknown: run time, memory, results. The ring-extraction sweeps (about 80 extractions per detector) are the likely slow part.
- With real output the number of rings at the net-value threshold could be large; the exporter keeps the best 500 by expected value (`--max-rings`) and records the total in `meta.json` [generated].
- The queue order is a heuristic on an uncalibrated score; it is not the validated label-based net value. Say so in any demo.
- At capture rate 1.0 the net-value rule may drift toward flagging everything with an illicit hit; read the cost sweep.
- Strict ring precision is pessimistic; `lenient_precision` is reported beside it.
- The Stage 03 velocity rule and tabular XGBoost differ from Stage 01's; do not mix them in one table.
- XGBoost can differ slightly between Windows and Linux; quote the platform.
- The velocity rule scored at chance on validation in Stage 01; communities do not recover rings; hub control only trims the giant component by 6 to 8 points. A Stage 03 negative finding must still be added to `docs/EVALUATION.md` after the real run.
- `config/fx_rates_inr.json` rates are approximate placeholders.
- Audit log: single shared token and free-text analyst names (does not prove who acted); tamper-evident, not tamper-proof; SQLite only until Stage 09 (Postgres free-tier limits are to be verified then). Rate limits are per process and per client address, which may be too coarse behind a proxy.
- Starlette's test client now wants `httpx2`; if pip cannot install it on your machine, tell me and the pin changes.
- Stage 05: metrics.json inner key names are the documented ones, not observed; any panel that does not recognise them says so. Send the first real metrics snapshot file.
- Stage 05: the case graph has no neighbour nodes because the bundle has none (plan: "strongest neighbours"). Decide whether to extend the exporter (schema version 2) in a later stage.
- Stage 05: offline mode downloads all of cases.json; check its size on real data (the sync script warns above 5 MiB).
- Stage 05: eslint 9.39.5 is pinned and flagged deprecated by npm; typescript is 5.9.3 (7.x exists but was not tried).
- Timestamps run to 18 Sep although the data is described as 10 days. CI never observed on GitHub.

## Pending from the owner

1. Stage 03 is still open: apply that zip, `pip install -r requirements.txt`, run `pytest`, `ruff check .`, `python scripts\check_docs.py`; run `python scripts\reproduce.py` twice on the real data; send the outputs, `docs\EVALUATION_RESULTS.md` [generated], `data\processed\hi_small\metrics.json` [generated] and `data\processed\hi_small\detect_report.json` [generated]; then git branch, merge, tag v0.4.0. Confirm v0.3.0 exists.
2. Stage 04: apply the zip over the Stage 03 tree (`pip install -r requirements.txt` again), run `pytest`, `ruff check .`, `python scripts\check_docs.py`; paste the outputs. After Stage 03 has run on the real data: `python scripts\export_snapshots.py`, then `python scripts\run_api.py`, and tell me what the queue looks like (number of rings, how long the export took). Report any ruff import-order complaints.
3. Add `data/audit/` [generated] to `.gitignore`. Decide whether to commit `data/snapshots/` [generated] (the plan says to commit the small bundle, but only once the Stage 03 numbers are frozen).
4. Git (Git Bash): branch `stage-04-snapshots-backend`, commit, push, PR, merge, tag v0.5.0.
5. Replace or accept the placeholder FX rates; confirm the buildathon deadline.
6. Stage 05: apply the zip, then from `frontend`: `npm ci`, `npm run check`, `npm run build`, `npm run dev`; from the root `pytest` (and `python scripts\check_docs.py`, `ruff check .`). Paste the outputs and tell me your Node version (`node -v`; 22.12 or newer needed). Report anything that looks wrong in the browser. Add nothing to the root `.gitignore` for the frontend (`frontend/.gitignore` covers it). Git: branch `stage-05-frontend-core`, merge, tag v0.6.0.

## Next: Stage 06 (AI layer)

Provider interface with a fake provider, graph tool functions, investigator loop with a call limit, pydantic case-file schema, verifier, devil's advocate pass, cache keyed by ring id, offline fallback; case files written into the bundle's `ai` block (schema change: bump or extend `SCHEMA_VERSION` deliberately), and the case page's Explanation card (`frontend/src/components/CaseView.tsx`, `AiCard`) to display them with their verification status. Needs from the owner: Groq and Gemini keys in `.env` (names `RS_LLM_PROVIDER`, `GROQ_API_KEY`, `GEMINI_API_KEY`) and the Stage 03 outputs. Do not start until the owner says "begin Stage 06".

## Continue-from-here prompt (paste into a new chat, with the project zip and this file attached)

```
You are my pair-programmer on RingSentinel (Razorpay AI Buildathon, Track 02, defense-only). First read HANDOVER.md, docs/PROJECT_EXPLAINER.md, docs/STAGE_04.md, docs/STAGE_05.md and docs/EVALUATION.md from the attached project zip, then follow the stage rules in the project instructions (prerequisites first, incremental zip with CHANGES_STAGE_NN.md containing only added or modified files, exact cmd commands, tests marked PASSED only if actually run here else NOT EXECUTED, docs and explainer updated, git workflow, caveats at the end).
State: Stages 00 to 05 are built; v0.2.0 tagged; v0.3.0 to v0.6.0 once I confirm (check git). Stage 03 has not been confirmed on the real data until I paste the reproduce.py output and docs/EVALUATION_RESULTS.md; Stages 04 and 05 have only seen synthetic, hand-made and demo data (Stage 05's metrics panels are unverified against real metrics.json). Wait for me to say "begin Stage 06", unless I paste the Stage 03 results first, in which case help me write the Stage 03 findings (including a negative one) into docs/EVALUATION.md.
Environment: Windows, cmd for everything except git (Git Bash), Python 3.13.3, dataset HI-Small (keep code switchable to HI-Medium). Your sandbox cannot reach Kaggle; rely on the files in the zip or on what I paste. The incremental zips do not contain earlier stages' source files: ask me for any file you need rather than guessing its signatures.
```
