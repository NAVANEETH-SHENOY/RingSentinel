# Changelog

One entry per tag. Format: Keep a Changelog style, Conventional Commit prefixes.

## v1.0.0 - Stage 09: deployment, final docs, diagram specs, demo (pending owner confirmation)

### Added
- Postgres audit store (`backend/app/audit_pg.py`): same hash chain, advisory lock on append, one connection per operation; `open_audit_log` and `backend_of` in `backend/app/audit.py`.
- Liveness route (no database access), `audit_backend` in health, 503 with `Retry-After` when the audit store is unreachable.
- `render.yaml`, `requirements-api.txt`, `frontend/vercel.json`, `.github/workflows/smoke.yml`, a Postgres job in `ci.yml`.
- `scripts/smoke_deployed.py` (deployed-site checks) and `scripts/sync_readme_results.py` (README tables generated from results files; called by `scripts/reproduce.py`).
- `docs/DEPLOYMENT.md`, `docs/DIAGRAM_SPECS.md`, `docs/DEMO_SCRIPT.md`, `docs/STAGE_09.md`, `RELEASE_NOTES_v1.0.0.md`; screenshots of the real bundle.
- Tests: `test_stage09_audit_pg.py`, `test_stage09_api.py`, `test_stage09_smoke.py`, `test_stage09_readme_sync.py`, `test_stage09_deploy.py`; two frontend tests.

### Changed
- README completed (results, findings, citations, limitations, deployment); `docs/EVALUATION.md`, `docs/ARCHITECTURE.md`, `docs/DATA.md`, `docs/PROJECT_EXPLAINER.md` and `HANDOVER.md` brought up to date.
- `requirements.txt` adds `psycopg[binary]==3.3.9`; API version 1.0.0; `.env.example` documents the Postgres URL.
- `frontend/.gitignore` no longer ignores `public/snapshots` (the deployed site needs it).

### Fixed
- The interface called cached output from the offline stand-in provider "Written by a language model (cached)"; it now says "Offline stand-in, not a language model".

## v0.9.0 - Stage 08: Elliptic second dataset, optional GraphSAGE, hardening (pending owner confirmation)

### Added
- Elliptic loader, split, graph features, detectors, per-step drift and results tables (`backend/ringsentinel/elliptic/`, `scripts/run_stage08.py`); synthetic Elliptic-format generator.
- Optional plain-PyTorch GraphSAGE (`requirements-gnn.txt`).
- API hardening: auth-failure lockout, trusted-proxy client address, body-size limit, security headers, docs switch.
- `scripts/secrets_scan.py`, `.github/workflows/audit.yml`.

### Changed
- `pyarrow` 22.0.0 to 23.0.1 (CVE-2026-25087).
- `.gitignore` now ignores kaggle.json and .kaggle/; `.env.example` gains Stage 08 names; rate limiter memory is bounded.

## v0.8.0 - Stage 07: human in the loop, feedback, drift, replay (pending owner confirmation)

Built on the owner's merged Stage 06 repo (main at f42a7e2, including the Groq provider changes).

### Added
- `backend/ringsentinel/review/feedback.py`: bounded threshold feedback (log-odds shift from net dismissals, hard ceilings), adjusted scores and values, live ordering; `GET /feedback` and `GET /queue?order=live` in `backend/app/routes.py`.
- `backend/ringsentinel/monitor/drift.py` (PSI per time window against the validation scores, warn and alert levels) and `backend/ringsentinel/monitor/replay.py` (detection time, assembly time, latency against the truth, timeline); `drift.json` and `replay.json` are now built by the exporter when scores and events exist.
- Frontend: decision panel with idempotent retry, live queue with the feedback card, drift page, replay page with a slider, quiet `refresh` in `useResource`.
- Tests: new backend tests (feedback, drift, replay, export, API and the scripted scenario) and new frontend tests; the demo bundle now carries drift, replay and template case files.
- `docs/STAGE_07.md`, drift and replay screenshots.

### Changed
- `backend/ringsentinel/snapshots/schemas.py`: drift and replay schemas carry the real fields when `status` is "ready"; the Stage 04 placeholders stay valid; `schema_version` is still "1".
- Settings: `RS_FEEDBACK_*` (API), `RS_PSI_*`, `RS_DRIFT_*`, `RS_REPLAY_STEPS` (export); `.env.example` lists them.
- `scripts/export_snapshots.py` gains `--no-monitor`; `scripts/make_demo_bundle.py` rebuilt on the real drift, replay and AI code.
- Docs: README, ARCHITECTURE, PROJECT_EXPLAINER, HANDOVER;
- No new dependency.

## v0.7.0 - Stage 06: AI layer (pending owner confirmation)

### Added
- `backend/ringsentinel/ai/`: case facts with account aliases, graph tools, typed-claim verifier, JSON tool-call investigator and devil's advocate, template fallback, cache keyed by ring hash, constrained natural-language query (validated JSON DSL), providers (Groq, Gemini, a deterministic fake) on the standard library.
- `backend/ringsentinel/snapshots/ai_merge.py`: merges AI blocks into the bundle (only the `ai` field of a case; recomputes hashes and `bundle_id`).
- `backend/ringsentinel/stage06.py`, `scripts/run_stage06.py`, `scripts/ai_query.py`.
- Case view: the Explanation card now shows the case file, the innocent explanation, the verifier status, the source (model, cached or rule-based) and a contested flag; model text is rendered as plain text.
- Tests: facts and tools, verifier (planted fake ids, counts, amounts), agent loop, pipeline and cache, query language, prompt injection, providers, bundle merge, API serving, settings; `frontend/tests/ai_card.test.tsx`.
- `docs/STAGE_06.md` with the prompt and schema listing.

### Changed
- Settings: LLM provider, model, timeout, pacing, tool budget, verify retries and LLM case limit (`RS_LLM_*`, `RS_AI_MAX_LLM_CASES`); API keys stay outside Settings.
- The `ai` schema in the bundle is now strict (`SCHEMA_VERSION` stays "1": the not-built placeholder is still valid); `export_snapshots` keeps AI blocks when `ai_cases.json` [generated] exists.
- `frontend/src/lib/types.ts`: `AiBlock` typed.
- No new dependency.

## v0.6.0 - Stage 05: frontend core (pending owner confirmation)

### Added
- `frontend/`: light-mode Next.js 16 static-export app: review queue, case view with a force-directed graph capped at 500 accounts by a deterministic rule, metrics dashboard (comparison table, ring PR curves, cost curve, ablations, robustness, latency), audit page (chain check, token-gated list), replay placeholder; loading, empty, error and offline states; works with the backend off.
- Data source with fallback: API, then saved snapshot, then built-in demo bundle; origin shown in the header.
- `scripts/make_demo_bundle.py` and the committed `frontend/public/demo-snapshots` (invented data, banner on every page); `scripts/sync_frontend_snapshots.py` to copy a validated real bundle into the frontend.
- Tests: 79 Vitest tests (graph cap, data source, every page, metrics extractors, contrast), `backend/tests/test_stage05_bundle.py`; `.github/workflows/frontend.yml`.
- `docs/STAGE_05.md`, `docs/screenshots/`.

### Changed
- Docs: README, ARCHITECTURE (C15), PROJECT_EXPLAINER, HANDOVER.

## v0.5.0 - Stage 04: snapshots and backend (pending owner confirmation)

### Added
- `backend/ringsentinel/snapshots/`: JSON Schemas for the six bundle files, a loader that checks schemas, SHA-256 hashes and cross references, and the deterministic exporter (D12); `scripts/export_snapshots.py`.
- `backend/app/`: FastAPI application factory, endpoints (health, queue, case, metrics, drift, replay, action, audit, audit verify), hash-chained SQLite audit log with idempotent actions and status rules, shared-token check, CORS, rate limiting, input validation (D13); `scripts/run_api.py`.
- Tests: exporter, audit log, API contract, settings and limiter, and an end-to-end test through the synthetic pipeline.
- `docs/STAGE_04.md`; API section in `docs/ARCHITECTURE.md`.

### Changed
- `requirements.txt`: adds `fastapi==0.162.5`, `uvicorn==0.54.0`, `httpx2==2.16.0` (tests only) and `jsonschema==4.26.0`.
- `.env.example`: Stage 04 variable names (`RS_GIT_COMMIT`, `RS_SNAPSHOT_DIR`, `RS_ANALYST_TOKEN`, `RS_AUDIT_DB_URL`, `RS_CORS_ORIGINS`, rate limits).
- Drift, replay and the AI case block are exported as explicit placeholders until Stages 06 and 07.

## v0.4.0 - Stage 03: detectors, ring extraction, evaluation (pending owner confirmation)

### Added
- `backend/ringsentinel/detect/`: tabular features and trailing 24-hour counts, design matrices from the Stage 02 window features, XGBoost and Isolation Forest fitting, and `SplitVault` (the test split is released once per detector).
- `backend/ringsentinel/rings/extract.py`: ring extraction from flagged transfers.
- `backend/ringsentinel/evaluate/`: metrics, Jaccard ring match, rupee cost model, per-detector report, cost sweep, latency.
- `backend/ringsentinel/stage03.py`, `scripts/run_stage03.py`, `scripts/reproduce.py`.
- `docs/EVALUATION.md` (protocol, rupee assumptions with justification, negative findings), `docs/STAGE_03.md`.
- Tests for all of the above, including a leakage test that rewrites the test split and a power check that does the same to validation.

### Changed
- Settings: neg_sample_frac, review/false-positive cost, loss capture rate, ring tau and minimum size, and the Stage 03 output paths; `.env.example` lists the new names.
- `requirements.txt`: pins `joblib==1.6.0` (already installed as a scikit-learn dependency; now imported directly). networkx is still not used or pinned.

## v0.3.0 - Stage 02: noise layer, graph with hub control, features (pending owner confirmation)

### Added
- `backend/ringsentinel/noise.py`: label-blind derived device, IP and VPA-handle attributes with an independence report.
- `backend/ringsentinel/graph/`: transfer graph builder, IDF weights and degree cap, pruning report, communities (components plus Louvain), giant-component ablation.
- `backend/ringsentinel/features/`: node and community features; `backend/ringsentinel/stage02.py` orchestration.
- `scripts/run_stage02.py`, `scripts/ablation_giant_component.py`.
- Tests for all of the above (132 tests in total after this stage).

### Changed
- Settings: `hub_cap`, `attr_cap`, `community_cap`, `louvain_resolution` and the Stage 02 output paths.
- `requirements.txt`: adds `igraph==1.0.0` and `scipy==1.16.3` (both have wheels for Python 3.11 to 3.13 on Windows and Linux). networkx is not used yet and is not pinned.

## v0.2.0 - Stage 01: data, temporal split and baselines

### Added
- `scripts/inspect_schema.py`: assumption-free schema inspector for the raw files, with tests.
- Ingestion (`backend/ringsentinel/ingest/`): header check, checksum manifest, patterns parser, chunked normalizer with pattern-derived labels and an INR amount.
- `backend/ringsentinel/split.py`: leakage-free temporal split with ring assignment.
- `backend/ringsentinel/models/baselines.py`: velocity rule and tabular XGBoost baselines.
- `backend/ringsentinel/evaluation/metrics.py`: precision, recall, F1, PR-AUC, best-F1 threshold.
- `scripts/run_stage01.py`: verify, ingest, split, baselines in one command.
- `docs/DATA.md`, `data/raw/MANIFEST.json`, `config/fx_rates_inr.json` (placeholder rates).

- `backend/ringsentinel/ingest/diagnose.py` and `scripts/diagnose_matching.py`: read-only diagnostic for pattern-to-CSV matching failures, with tests.

### Changed
- Corrected HI-Small download (adds the `Is Laundering` column): manifest checksums refreshed, `is_illicit` now comes from that column, label note in `baseline_metrics.json` now reads the real label source, stale "no label column" statements removed from code and docs, real-data header test accepts both layouts.
- Settings gain split fractions and per-variant file paths; version 0.2.0.
- Pinned numpy, pandas, pyarrow, scikit-learn and xgboost.

## v0.1.0 - Stage 00: environment and scaffold

### Added
- Repository layout, pinned `requirements.txt`, `pyproject.toml` (pytest and ruff config).
- `backend/ringsentinel/config.py`: validated settings with a single dataset-variant switch (HI-Small default; HI-Medium supported without code changes).
- `scripts/check_docs.py` and its tests: fails when docs name a missing file or function.
- GitHub Actions workflow running ruff, check_docs and pytest on Ubuntu and Windows.
- Docs skeleton: README, ARCHITECTURE, PROJECT_EXPLAINER, STAGE_00, HANDOVER.
- `.gitignore`, `.gitattributes` (LF line endings), `.env.example` (names only).
- Frontend shell `frontend/package.json` (no dependencies yet).
