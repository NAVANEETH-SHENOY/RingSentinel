# RingSentinel: zero-context project explainer

Written for a reader (human or LLM) who has only the project zip. Current milestone: **Stage 09 (M9), release v1.0.0: deployment files, a Postgres audit store, a deployed-site smoke test, final docs, diagram specs and a demo script, on top of Stages 01 to 08.** The pipeline has been run on the real IBM AML HI-Small data (seed 42) and on Elliptic by the owner; the committed bundle (`data/snapshots/`, bundle id starting `af65200a`) is marked `evaluation_frozen: false` until the owner freezes it. The three hosting services (Vercel, Render, Neon) have not been exercised by the builder. Anything that does not exist is marked [planned]. If this file and the code disagree, the code wins; run `python scripts/check_docs.py` to catch stale paths.

## 1. Plain-language summary

RingSentinel is a tool for fraud analysts. Money moves between accounts. Sometimes groups of accounts work together to move illicit money, which is hard to see one transaction at a time. RingSentinel will link accounts through the transfers between them, find groups that behave like a coordinated ring, rank the groups by how worthwhile they are to review, and explain each one. A human analyst then confirms, dismisses or holds each case; the tool never blocks anything itself. It is judged on honest measurement: how many real rings it finds, how many false alarms it raises, and what those false alarms cost in rupees.

It is built for the Razorpay AI Buildathon, Track 02 (AI Risk Manager), as a solo project, and it is defense-only. It uses a public synthetic dataset (IBM anti-money-laundering transactions), not real customer data.

The project can load and clean that dataset, label the known laundering rings, split the data by time, turn the transfers into an account graph with hub control and a table of per-account and per-community features, score every transfer with four detectors (including one that uses the graph features), group flagged transfers into candidate rings, and measure everything on a held-out test period, including the rupee cost of false alarms. The measurement code has been run on the real data; the headline result is that adding graph features to the same model raises test PR-AUC from 0.204 to 0.614 (synthetic data, one seed). The results are packaged into a small snapshot bundle and served by a local API that ranks the flagged rings for review and records each analyst decision (confirm, dismiss or hold) in a tamper-evident log, where every entry carries a fingerprint of the one before it.

A web interface shows the ranked queue, each ring as a graph of transfers, the evaluation metrics, the audit log, a drift page and a replay page. For each flagged ring an AI assistant writes a short plain-language explanation and the best innocent explanation, and a checker confirms every number and account it mentions against the real transfers; if anything fails, a plain rule-based summary is shown instead. The AI never changes a score or takes an action. New in Stage 07: the analyst can confirm, dismiss or hold a ring in the interface. Dismissals nudge the review threshold up a little, inside fixed limits, and the queue re-ranks itself; the drift page warns when the detector's scores move away from what it was validated on; the replay page steps through the test period and shows when each ring became detectable. Stage 09 adds the files to deploy it on free hosting (a static site, a small API, a Postgres decision log), a script that checks the deployed site, and a demo script.

## 2. Technical summary

- Stack: Python 3.10+ (owner uses 3.13), pandas, numpy, pyarrow, scikit-learn, XGBoost, pydantic, pytest, ruff, scipy, python-igraph, joblib, all pinned in `requirements.txt`. FastAPI, uvicorn, jsonschema and SQLite (Stage 04; httpx2 for tests). Stage 05: Next.js 16 (static export), React 19, TypeScript, d3-force, Vitest and Testing Library (all under `frontend/`). Stage 09: psycopg 3 (Postgres audit log) and `requirements-api.txt` (the slim runtime set for the host). networkx is not used (ring splitting reuses the igraph code).
- Architecture: a deterministic offline pipeline (ingest, temporal split, graph, features, detectors, ring extraction, evaluation) exports static JSON snapshots; a thin API and a UI sit on top [planned]. See `docs/ARCHITECTURE.md`.
- Implemented now: (D1) checksum manifest; (D2) chunked CSV reader to a typed event table, pattern parser, label attachment, INR amount, validation; (D4) time-based split with ring assignment; two baselines (velocity rule; tabular XGBoost) scored on the validation split; shared metrics; (D3) label-blind synthetic noise layer; (D5) cumulative past-only transfer graph per window with IDF edge weights, a degree cap tuned on validation, a pruning report and Louvain-split communities; (D6) node and community features; (D7) four detectors scored per transfer (velocity rule, tabular XGBoost, graph-feature XGBoost, Isolation Forest) with a guard that releases the test split once per detector; (D8) ring extraction from the flagged transfers; (D9) transaction-level and ring-level metrics, rupee net-value threshold, cost sweep, ablations (hub control and graph features on/off), robustness (edge dropout) and detection latency, regenerated by `scripts/reproduce.py`.
- (D12) snapshot exporter: Stage 03 outputs to six schema-validated JSON files tied together by SHA-256 hashes; (D13) FastAPI backend serving them from memory, with a hash-chained SQLite audit log, idempotent actions, token check, CORS and rate limiting.
- (C15, Stages 05 and 07) Next.js interface: queue (live order and feedback card), case view with a force-directed graph capped at 500 accounts, decision panel, AI explanation card, metrics dashboard, audit page, drift page, replay page; reads the API when it answers, else the snapshot files, else a built-in demo bundle. Decisions need the API.
- (D10, Stage 06) AI layer: per-ring case file and devil's advocate written by an LLM over graph tools, every cited number recomputed by a verifier, template fallback, cache keyed by ring hash, validated JSON query language, merged into the bundle's `ai` field only. The LLM never changes a score.
- (Stage 07) Bounded analyst feedback (`backend/ringsentinel/review/feedback.py`): net dismissals shift the review threshold in log-odds by a fixed step up to a maximum, with hard ceilings in code; confirmations only cancel dismissals and never lower the threshold below the validated one; holds change nothing. The same shift re-ranks the open rings by an adjusted expected value. The API serves it (`annotate()` in `backend/ringsentinel/review/feedback.py`, `/queue?order=live`, `GET /feedback`).
- (D11, Stage 07) Drift (`backend/ringsentinel/monitor/drift.py`): population stability index of each equal-width time window of the test period against the validation scores, with warn and alert levels. Replay (`backend/ringsentinel/monitor/replay.py`): per ring the time its flagged transfers first touch the minimum ring size, assembly time, and latency against the true ring where one supplies most transfers.
- Stage 09: Postgres audit store (`backend/app/audit_pg.py`), liveness route, 503 on an unreachable audit store, `render.yaml`, `frontend/vercel.json`, `scripts/smoke_deployed.py`, `scripts/sync_readme_results.py`, `docs/DEPLOYMENT.md`, `docs/DIAGRAM_SPECS.md`. Still to come [planned]: a validation of the feedback rule, individual analyst accounts, a real-model evaluation of the AI layer.
- One setting, `RS_DATASET_VARIANT`, selects HI-Small (default), LI-Small, HI-Medium or LI-Medium; all paths derive from it.

## 3. Current state

**Stage 09 (M9, release v1.0.0, built in the sandbox; owner's run pending):**

| Item | State |
| --- | --- |
| Verified in the sandbox | Backend 733 passed and 8 skipped with `RS_TEST_POSTGRES_URL` set (a local Postgres 16), 721 passed and 20 skipped without it; `ruff check .` clean; `scripts/check_docs.py` OK; frontend 122 Vitest tests pass; the API run from `requirements-api.txt` alone served the real bundle with a Postgres log and passed `scripts/smoke_deployed.py` against the built static site (44 passed, 0 failed, 1 warning: not frozen) |
| Not verified | Anything on Vercel, Render or Neon; Render's `X-Forwarded-For` hop count (set to 2, inferred); Neon scale-to-zero behaviour; GitHub Actions for the new jobs |
| Real results | HI-Small test PR-AUC: velocity 0.0014, Isolation Forest 0.0052, tabular XGBoost 0.2040, graph XGBoost 0.6145; ring precision 0.2647 and recall 0.3789 for the graph model; Elliptic graph 0.772 against local 0.768. Tables: `docs/EVALUATION_RESULTS.md` [generated], `docs/RESULTS_TABLE.md` [generated], README |
| Bundle | 500 of 3,638 test rings exported; case files: 400 template, 99 offline stand-in (shown as such), 1 real Groq call |
| Does not exist | Live URLs, a recorded demo video, frozen numbers, individual analyst accounts, Postgres backups, validation of the feedback rule |


**Stage 08 (M8, built in the sandbox; owner's run pending):** a second dataset path (Elliptic, transaction level), an optional GraphSAGE, API hardening and a secrets and dependency review. Elliptic has never run on the real files (not downloadable from the sandbox): every Elliptic number so far comes from SYNTHETIC files. See the Stage 08 rows added to sections 4 to 13 and `docs/STAGE_08.md`.

| Item | State |
| --- | --- |
| Milestone | M0 and M1 (Stage 01) done and confirmed on the owner's Windows machine, pushed. M2 / Stage 02 built; builder ran it on the real data; owner's run not seen. M3 / Stage 03 built and tested on synthetic data in the builder's sandbox; owner's run and the real-data run are pending. M4 / Stage 04 built on top of it and tested in the builder's sandbox; owner's run pending. M5 / Stage 05 and M6 / Stage 06 built in the builder's sandbox (the owner had not run them); M7 / Stage 07 folds both in and is tested in the builder's sandbox; owner's run, merge and tag v0.8.0 pending |
| Works (tested on synthetic data; Stage 01 and 02 also on the real HI-Small files) | Everything in Stage 01 and Stage 02, plus: tabular features and velocity counts, design matrices, the four detectors, the test-split vault, ring extraction, Jaccard ring match, cost model, per-detector report, cost sweep, latency, ablation, robustness, result tables, `scripts/run_stage03.py`, `scripts/reproduce.py` |
| Verified on the real files | Stage 01 (owner: 85 tests passed, pipeline run) and Stage 02 (builder's run of every step). Stage 03: nothing; it has not touched the real files |
| Works, Stage 04 (hand-made and synthetic data only) | Snapshot exporter and loader, JSON schemas, ranking by expected value, case edges, hash-chained audit log with tamper detection, action rules and idempotency, all API endpoints, token check, CORS, rate limiting, `scripts/export_snapshots.py`, `scripts/run_api.py`. A real uvicorn process was started and queried once in the builder's sandbox |
| Works, Stage 06 (fake provider, synthetic and hand-made data; template and fake run also on the owner's real 500-ring bundle in the builder's sandbox) | Case facts and aliases, graph tools, verifier, investigator and devil's advocate loops, template fallback, cache, query DSL, Groq and Gemini HTTP clients (against a fake transport only), bundle merge, `scripts/run_stage06.py`, `scripts/ai_query.py`. **No live model call has ever been made**, so the real verified share is unknown |
| Works, Stage 05 | Read-only UI for queue, case graph (500-account cap), metrics, audit, replay placeholder; API-first with snapshot and demo fallback; `scripts/make_demo_bundle.py`, `scripts/sync_frontend_snapshots.py`. Checked in the builder's sandbox: 79 Vitest tests, type check, lint, production build, and a headless Chrome run against a real uvicorn process serving the demo bundle |
| Works, Stage 07 (synthetic world and demo bundle only) | Threshold feedback and live queue (`/queue?order=live`, `GET /feedback`), the decision panel (idempotent retry, status rules), drift (PSI per window, warn and alert levels), replay (assembly time, latency against the truth, deterministic), the full AI card (source, verifier badge, devil's advocate, contested note), the scripted analyst scenario in both the API and the UI. Checked in the builder's sandbox: backend and frontend test suites, type check, lint, production build, headless Chrome screenshots of the drift, replay and case pages on the demo bundle |
| Does not exist yet | Live LLM results, any Stage 03 result on real data (so drift and replay have never run on real data), validation of the feedback rule, deployment, Postgres |
| Headline numbers | None. Stage 03 produces them when `scripts/reproduce.py` is run on the real data (`docs/EVALUATION_RESULTS.md` [generated]). Validation-split Stage 01 baselines exist; Stage 02 reports graph diagnostics only |

## 4. Repo map

| Path | What it does | Called by | Calls |
| --- | --- | --- | --- |
| `README.md`, `HANDOVER.md`, `CHANGELOG.md` | Overview, continue-in-new-chat file, release notes | Humans; `scripts/check_docs.py` reads the first two | none |
| `requirements.txt`, `pyproject.toml` | Pinned dependencies; pytest and ruff settings | pip, pytest, ruff | none |
| `.env.example` | Env var names only | Humans; `backend/ringsentinel/config.py` reads `.env` | none |
| `.github/workflows/ci.yml` | CI: ruff, check_docs, pytest on Ubuntu and Windows | GitHub | `scripts/check_docs.py`, pytest |
| `config/fx_rates_inr.json` | Placeholder INR rate per currency | `load_fx_rates()` | none |
| `data/raw/MANIFEST.json` | Size and SHA-256 of the raw HI-Small files | `run_verify()` | none |
| `data/raw/`, `data/processed/`, `data/snapshots/` | Data folders; raw and processed are gitignored | pipeline | none |
| `backend/ringsentinel/config.py` | `Settings`, `get_settings()`: variant, data dir, seed, split fractions, all file paths | everything | python-dotenv, pydantic |
| `backend/ringsentinel/ingest/schema.py` | Expected raw header, internal column names, `check_header()` | normalize | none |
| `backend/ringsentinel/ingest/manifest.py` | Checksums: `build_entry()`, `verify_files()`, `add_variant()` | `backend/ringsentinel/stage01.py` | hashlib |
| `backend/ringsentinel/ingest/patterns.py` | `parse_patterns()`: patterns file to a table with ring_id and ring_type | normalize | pandas |
| `backend/ringsentinel/ingest/normalize.py` | `read_transactions()`, `add_amount_inr()`, `attach_labels()`, `build_rings_truth()`, `validate_events()`, `normalize()` | `run_ingest()` | patterns, schema, config |
| `backend/ringsentinel/split.py` | `compute_cuts()`, `assign_split()`, `check_no_overlap()`, `build_split()` | `run_split()` | numpy, pandas |
| `backend/ringsentinel/evaluation/metrics.py` | `precision_recall_f1()`, `average_precision()`, `best_f1_threshold()`, `evaluate_scores()` | `run_baselines()` | numpy |
| `backend/ringsentinel/models/baselines.py` | `trailing_counts()`, `velocity_scores()`, `tabular_features()`, `train_xgb()` | `run_baselines()` | xgboost |
| `backend/ringsentinel/stage01.py` | Orchestration: `run_verify()`, `run_ingest()`, `run_split()`, `run_baselines()`, `prepare_baseline_frames()` | `scripts/run_stage01.py` | all of the above |
| `backend/ringsentinel/noise.py` | `build_noise()`, `attribute_degree()`, `independence_report()`: synthetic derived device, IP and VPA-handle attributes (label-blind) | `run_noise()` | numpy, pandas |
| `backend/ringsentinel/graph/hubs.py` | `idf_weight()`, `hub_mask()`, `choose_hub_cap()`, `effective_hub_cap()` | graph builder, `run_tune()` | numpy |
| `backend/ringsentinel/graph/build.py` | `TransferGraph`, `cumulative_events()`, `build_graph()`, `pruning_report()` | features, `run_features()`, ablation | hubs |
| `backend/ringsentinel/graph/communities.py` | `component_labels()`, `detect_communities()` (components, then igraph Louvain for oversized ones) | `build_window_features()` | igraph, scipy |
| `backend/ringsentinel/graph/ablation.py` | `attribute_links()`, `giant_component_rows()`, `format_ablation_table()` | `run_ablation()` | noise, communities |
| `backend/ringsentinel/features/node.py` | `node_features()`, `pagerank()`, `hourly_groups()` | `build_window_features()` | scipy |
| `backend/ringsentinel/features/community.py` | `community_features()`, `attach_to_nodes()` | `build_window_features()` | node.py |
| `backend/ringsentinel/features/build.py` | `build_window_features()`: graph, node features, communities, community features for one window; reads only four columns | `run_features()` | graph, features |
| `backend/ringsentinel/stage02.py` | Orchestration: `run_noise()`, `run_tune()`, `run_features()`, `run_ablation()`, `load_events()`, `ring_accounts()` | `scripts/run_stage02.py` | all of the above |
| `backend/ringsentinel/detect/tabular.py` | Per-transfer columns and trailing 24-hour counts: `trailing_counts()`, `tabular_frame()` | `load_prepared()` | numpy, pandas |
| `backend/ringsentinel/detect/matrix.py` | Design matrices: `graph_columns()`, `window_table()`, `feature_names()`, `design_matrix()` | `matrix_for()` | numpy, pandas |
| `backend/ringsentinel/detect/models.py` | `sample_rows()`, `fit_xgb()`, `score_chunks()`, `xgb_predict()`, `ImputedIsolationForest` | `run_detect()`, `run_ablate()` | xgboost, scikit-learn |
| `backend/ringsentinel/detect/guard.py` | `SplitVault`: train and validation for fitting; test released once per detector | `make_vault()` | none |
| `backend/ringsentinel/rings/extract.py` | `extract_rings()`: flagged transfers to rings (components, Louvain above the cap) | `Scored.rings()` | `detect_communities()` |
| `backend/ringsentinel/evaluate/metrics.py` | `average_precision()`, `precision_recall_f1()`, `best_f1_threshold()`, `pr_curve()` | `evaluate_detector()` | numpy |
| `backend/ringsentinel/evaluate/ringmatch.py` | `jaccard()`, `match_rings()`, `ring_metrics()` | `ring_block()` | numpy |
| `backend/ringsentinel/evaluate/cost.py` | `cost_terms()`, `net_value()`, `choose_nv_threshold()` | `evaluate_detector()`, `cost_sweep()` | numpy |
| `backend/ringsentinel/evaluate/report.py` | `Scored`, `candidate_thresholds()`, `ring_block()`, `txn_block()`, `latency_block()`, `evaluate_detector()`, `cost_sweep()` | `run_evaluate()`, `run_ablate()` | rings, metrics, cost |
| `backend/ringsentinel/stage03.py` | Orchestration: `load_prepared()`, `run_detect()`, `run_evaluate()`, `run_ablate()`, `run_robustness()`, `build_uncontrolled_features()`, `format_full_results()`, `numeric_differences()` | `scripts/run_stage03.py`, `scripts/reproduce.py` | all of the above, Stage 02 builders |
| `scripts/run_stage03.py` | Command line for Stage 03 steps | owner | `backend/ringsentinel/stage03.py` |
| `scripts/reproduce.py` | Reruns Stage 03, compares with the previous metrics.json [generated], writes `docs/EVALUATION_RESULTS.md` [generated] | owner | `backend/ringsentinel/stage03.py` |
| `backend/tests/s03_world.py` | Synthetic dataset in the real layout for the Stage 03 tests | Stage 03 and 04 tests | none |
| `backend/ringsentinel/snapshots/schemas.py` | `SCHEMA_VERSION`, one JSON Schema per bundle file (`SCHEMAS`), `RING_ID_PATTERN` | bundle loader, API schemas | none |
| `backend/ringsentinel/snapshots/bundle.py` | `canonical_text()`, `clean()`, `validate_document()`, `load_bundle()`, `SnapshotError`: read and validate a bundle (schemas, hashes, queue and cases agree) | exporter, `SnapshotStore` | jsonschema, schemas |
| `backend/ringsentinel/snapshots/export.py` | `ring_id_for()`, `expected_value_inr()`, `build_documents()`, `write_bundle()`, `export_snapshots()`: D12 | `scripts/export_snapshots.py`, tests | bundle, pandas (reads `events.parquet` [generated] for case edges) |
| `scripts/export_snapshots.py` | Command line for D12 | owner | `export_snapshots()` |
| `backend/app/config.py` | `AppSettings`, `load_app_settings()`: API environment variables | `create_app()` | `ringsentinel.config` |
| `backend/app/store.py` | `SnapshotStore`: bundle held in memory | `create_app()`, routes | `load_bundle()` |
| `backend/app/audit.py` | `AuditLog`: `append()`, `verify()`, `statuses()`; `entry_hash()`, `request_digest()`, `allowed_actions()`, `sqlite_path_from_url()` | routes | sqlite3 |
| `backend/app/ratelimit.py` | `RateLimiter.check()`: sliding window per client and bucket | middleware in `create_app()` | none |
| `backend/app/schemas.py` | `ActionRequest` (validated body), `ActionResponse`, `AuditEntry`, `VerifyResponse` | routes | pydantic |
| `backend/app/routes.py` | All endpoints; `require_token()` | `create_app()` | store, audit, schemas |
| `backend/app/main.py` | `create_app()`: loads the bundle (fails fast), opens the audit log, adds CORS and the rate-limit middleware | `scripts/run_api.py`, tests | all of `backend/app/` |
| `scripts/run_api.py` | Starts uvicorn on 127.0.0.1:8000 | owner | `create_app()` |
| `backend/tests/s04_bundle.py` | Hand-made Stage 03 outputs with exact numbers | Stage 04 tests | none |
| `scripts/run_stage02.py` | Command line for Stage 02 | owner | `backend/ringsentinel/stage02.py` |
| `scripts/ablation_giant_component.py` | Prints the giant-component table with and without hub control | owner | `run_ablation()` |
| `backend/tests/toy_events.py` | Hand-built event tables for the Stage 02 tests | Stage 02 tests | none |
| `backend/ringsentinel/ingest/diagnose.py` | Read-only matching diagnostic: `diagnose_matching()`, `format_diagnosis()`, `diagnose_legs()`, `format_legs()`, `diagnose_account_columns()`, `format_account_columns()` | `scripts/diagnose_matching.py` | `read_transactions()` output, `parse_patterns()` output |
| `scripts/diagnose_matching.py` | Prints and saves which field disagrees between patterns file and CSV | owner | `backend/ringsentinel/ingest/diagnose.py` |
| `scripts/run_stage01.py` | Command line for Stage 01 | owner | `backend/ringsentinel/stage01.py` |
| `scripts/inspect_schema.py` | Prints real columns and layout of the raw files (standard library only) | owner | none |
| `scripts/check_docs.py` | Fails if docs name a missing path or function | CLI, CI, tests | filesystem |
| `backend/tests/conftest.py` | Builds a synthetic dataset in the real layout | all data tests | none |
| `backend/tests/test_*.py` | See section 8 | pytest | the code under test |
| `frontend/package.json`, `frontend/package-lock.json` | Pinned frontend dependencies and scripts (`dev`, `build`, `check`, `test`) | npm | none |
| `frontend/next.config.mjs`, `frontend/tsconfig.json`, `frontend/eslint.config.mjs`, `frontend/vitest.config.mts`, `frontend/vitest.setup.ts` | Static export, TypeScript, lint and test setup | Next, tsc, eslint, vitest | none |
| `frontend/.env.example`, `frontend/.gitignore` | Frontend env var names; ignores the real bundle copy | Humans, git | none |
| `frontend/src/app/layout.tsx`, `frontend/src/app/globals.css` | Root layout (wraps pages in `AppShell`) and all styles (palette variables) | Next | `frontend/src/components/AppShell.tsx` |
| `frontend/src/app/page.tsx`, `frontend/src/app/case/page.tsx`, `frontend/src/app/metrics/page.tsx`, `frontend/src/app/audit/page.tsx`, `frontend/src/app/replay/page.tsx`, `frontend/src/app/drift/page.tsx`, `frontend/src/app/not-found.tsx` | Route files; each renders one view (the case page reads `?id=` and wraps in Suspense) | Next | the matching component |
| `frontend/src/components/AppShell.tsx` | Header, nav, data-source chip, demo / not-frozen / out-of-date banners; provides the data source | `frontend/src/app/layout.tsx` | `SourceProvider`, `useSource` |
| `frontend/src/components/QueueView.tsx` | Ranked table, search, status filter, paging; live or exported order; live columns and the feedback card when the API answers | `frontend/src/app/page.tsx` | `useSource`, `useResource`, `FeedbackCard`, `liveLabel` |
| `frontend/src/components/CaseView.tsx`, `frontend/src/components/ForceGraph.tsx` | One ring: stats, decision panel, SVG graph, signals, explanation card (`AiCard`, defined in this file), link table, members | case page | `capGraph`, `layoutGraph`, `ActionPanel`, `AiCard` |
| `frontend/src/components/MetricsView.tsx`, `frontend/src/components/charts.tsx` | Dashboard panels and the SVG line chart and bars | metrics page | `frontend/src/lib/metricsView.ts`, `frontend/src/lib/markdownTable.ts` |
| `frontend/src/components/AuditView.tsx`, `frontend/src/components/DataState.tsx`, `frontend/src/components/StatusChip.tsx` | Audit page (chain check, token, list), loading, empty and error states, chips | pages | `frontend/src/lib/source.ts` |
| `frontend/src/lib/source.ts` | `createSource`: API, then snapshot, then demo, with timeouts, schema-version check and a cached cases.json; `queue(order)`, `feedback()`, `act()` (needs the API and the token); `DataUnavailableError`, `SchemaVersionError` | all views via context | `frontend/src/lib/http.ts`, `frontend/src/lib/config.ts` |
| `frontend/src/lib/http.ts` (`getJson`, `postJson`), `frontend/src/lib/config.ts`, `frontend/src/lib/types.ts`, `frontend/src/lib/format.ts`, `frontend/src/lib/token.ts` | Fetch with timeout, env config, bundle and API types, INR and number formatting, per-tab token storage | source, views | none |
| `frontend/src/lib/graph.ts` | `buildNodes`, `capGraph` (500-account cap), `layoutGraph` (deterministic d3-force) | ForceGraph.tsx | d3-force |
| `frontend/src/lib/metricsView.ts`, `frontend/src/lib/markdownTable.ts` | Tolerant extractors for D9 metrics; markdown table parser | MetricsView.tsx | none |
| `frontend/src/lib/useResource.ts`, `frontend/src/lib/SourceContext.tsx` | Load-state hook (`reload` shows the spinner, `refresh` reloads quietly and keeps the page); context holding the source | views | none |
| `frontend/public/demo-snapshots` | Committed DEMO bundle (invented data) | `createSource` (last fallback) | none |
| `frontend/public/snapshots` | Real bundle copy [generated], git-ignored | `createSource` | none |
| `scripts/make_demo_bundle.py` | Builds and validates the demo bundle (`build_demo_documents()`, `main()`); drift, replay and template case files come from the real Stage 06 and 07 code on invented data | owner | `ring_id_for()`, `expected_value_inr()`, `write_bundle()`, `load_bundle()`, `compute_drift()`, `compute_replay()`, `build_ai_cases()` |
| `scripts/sync_frontend_snapshots.py` | `sync()`: validate a bundle with `load_bundle()`, copy it into the frontend | owner | `load_bundle()` |
| `.github/workflows/frontend.yml` | CI for the frontend: type check, lint, tests, build | GitHub | npm scripts |
| `frontend/tests/*.test.ts*` | See section 8 | vitest | the code under test |
| `backend/tests/test_stage05_bundle.py` | Demo bundle and sync script against the real loader | pytest | both scripts |
| `docs/*.md` | Architecture, data facts, per-stage notes, this file | Humans | none |

Stage 06 files (what each does; callers and callees in the last two columns):

| Path | What it does | Called by | Calls |
| --- | --- | --- | --- |
| `backend/ringsentinel/ai/schemas.py` | Strict pydantic models `CaseFile`, `BenignCase`, `CountClaim`, `AmountClaim`; closed metric vocabularies; `PROMPT_VERSION` | investigator, verifier, template | pydantic |
| `backend/ringsentinel/ai/facts.py` | `CaseFacts`: aliases, edges, coverage, recomputation of every claimable number, cycle test | pipeline, tools, verifier, prompts | none |
| `backend/ringsentinel/ai/tools.py` | `ToolBox`: `community_stats`, `edge_weights`, `get_neighbors`, `get_timeline` (read-only, capped rows) | `run_agent()` | `CaseFacts` |
| `backend/ringsentinel/ai/verifier.py` | `verify()`: recomputes typed claims and scans prose for unknown aliases, dates, numbers | `run_agent()`, `explain_case()` | `CaseFacts` |
| `backend/ringsentinel/ai/prompts.py` | System prompts, context builders, `read_tagged_json()` | investigator | `CaseFacts` |
| `backend/ringsentinel/ai/investigator.py` | `run_agent()` tool-call loop with budget and verify retries; `investigate()`, `devils_advocate()`, `contested()` | `explain_case()` | provider, tools, verifier |
| `backend/ringsentinel/ai/template.py` | `template_case_file()`: rule-based fallback from the data only | `explain_case()` | `CaseFacts` |
| `backend/ringsentinel/ai/cache.py` | `input_hash()`, `CaseCache` (atomic JSON files keyed by hash) | `explain_case()` | none |
| `backend/ringsentinel/ai/pipeline.py` | `explain_case()`, `build_ai_cases()`, `summarize()`, `ai_document()` | `run_ai()` | the other `ai` modules |
| `backend/ringsentinel/ai/provider.py` | `GroqProvider`, `GeminiProvider`, `ResilientProvider`, `make_provider()`; keys from the environment only | `run_ai()` | urllib |
| `backend/ringsentinel/ai/fake.py` | `HeuristicProvider`: deterministic offline model for tests and demos | `make_provider("fake")` | none |
| `backend/ringsentinel/ai/query.py` | `parse_query()`, `run_query()`, `translate()`: validated JSON DSL over queue rows | `scripts/ai_query.py` | provider |
| `backend/ringsentinel/snapshots/ai_merge.py` | `apply_ai_blocks()`, `merge_ai_into_bundle()`: only the `ai` field of a case; validates before writing | `export_snapshots()`, `run_ai()` | schemas, bundle |
| `backend/ringsentinel/stage06.py` | `run_ai()`, `format_report()`, `options_from()` | `scripts/run_stage06.py` | pipeline, merge |
| `scripts/run_stage06.py`, `scripts/ai_query.py` | Command lines for Stage 06 | owner | `run_ai()`, `run_query()` |
| `backend/tests/s06_cases.py` | Hand-made rings and valid model replies | Stage 06 tests | none |

Stage 07 files:

| Path | What it does | Called by | Calls |
| --- | --- | --- | --- |
| `backend/ringsentinel/review/feedback.py` | `FeedbackConfig` (validated, hard ceilings), `threshold_offset()`, `effective_threshold()`, `adjusted_score()`, `count_decisions()`, `annotate()` (status and live fields per queue item, plus the state), `export_order()` | `backend/app/routes.py` | `expected_value_inr()` |
| `backend/ringsentinel/monitor/drift.py` | `reference_bins()`, `bin_shares()`, `psi_from_shares()`, `classify()`, `window_edges()` (exact integer edges), `compute_drift()`, `build_drift_document()`, `not_built()` | `build_documents()` | numpy, pandas |
| `backend/ringsentinel/monitor/replay.py` | `ring_timing()`, `compute_replay()`, `build_replay_document()` | `build_documents()` | `window_edges()` |
| `backend/ringsentinel/snapshots/export.py` | `build_documents(..., with_monitor=True)` builds drift and replay (placeholders when scores or events are missing) | `export_snapshots()` | the two monitor modules |
| `backend/app/routes.py` | `GET /queue` (`order=export|live`, status and live fields), `GET /feedback` | the API | `annotate()` |
| `backend/app/config.py` | `AppSettings.feedback_config()`; `RS_FEEDBACK_*` | `create_app()` | `FeedbackConfig` |
| `frontend/src/components/ActionPanel.tsx` | Decision form: name, token, note, buttons per status (`allowedActions`), error messages per status code, one idempotency key per attempt | CaseView.tsx | `source.act()`, `newIdempotencyKey` |
| `frontend/src/components/FeedbackCard.tsx` | Threshold shift, counts, limit notice, rule text | QueueView.tsx | none |
| `frontend/src/components/DriftView.tsx`, `frontend/src/components/monitorCharts.tsx` | Drift page (status, PSI bars `DriftChart`, window table); `TimelineChart` for the replay | pages | `source.drift()` |
| `frontend/src/components/ReplayView.tsx` | Replay page: slider and step buttons, detected-so-far table, summary | replay page | `detectedBy`, `eventsBy` |
| `frontend/src/lib/replayView.ts`, `frontend/src/lib/liveQueue.ts`, `frontend/src/lib/idempotency.ts` | Replay arithmetic (`stepEndMs`, `detectedBy`, `eventsBy`, `formatMinutes`); `liveLabel`, `hasLive`; `newIdempotencyKey` | views | none |
| `frontend/src/app/drift/page.tsx` | Route file for the drift page | Next | `DriftView` |
| `backend/tests/s07_world.py` | Synthetic world through Stage 02 and 03 and the export, shared by Stage 07 tests | Stage 07 tests | `write_world()`, `export_snapshots()` |

Planned (created in the stage named): `docs/DIAGRAM_SPECS.md` [planned, Stage 09]. Note the two metric packages: `backend/ringsentinel/evaluation/metrics.py` is Stage 01's (used by the Stage 01 baselines); `backend/ringsentinel/evaluate/metrics.py` and its neighbours are Stage 03's. Stage 03 code does not import the Stage 01 package.

### Stage 08 additions

| Path | What it does | Called by / calls |
| --- | --- | --- |
| `backend/ringsentinel/elliptic/settings.py` | `EllipticSettings`, `load_elliptic_settings()`: split steps, hub cap, paths | called by every Elliptic module and `scripts/run_stage08.py`; wraps core `Settings` |
| `backend/ringsentinel/elliptic/schema.py` | Expected file names, column counts, class codes (all VERIFY) | used by the loader |
| `backend/ringsentinel/elliptic/load.py` | `read_features`, `read_classes`, `read_edges`, `assemble`, `load_elliptic` -> `EllipticData` | calls the schema module; called by the pipeline module |
| `backend/ringsentinel/elliptic/split.py` | `assign`, `split_nodes`, `step_to_ts` (pseudo date so `check_no_overlap` can run) | calls `ringsentinel.split` |
| `backend/ringsentinel/elliptic/graph.py` | `edge_table`, `window_frames`, `graph_matrix`, `GRAPH_COLUMNS` allow-list | calls `features.build.build_window_features` |
| `backend/ringsentinel/elliptic/pipeline.py` | `run_elliptic()`, `fit_detector`, `evaluate_detector`, per-step PSI, `cross_dataset_table()` | calls `detect.models`, `evaluate.metrics`, `monitor.drift`, `SplitVault` |
| `backend/ringsentinel/elliptic/gnn.py` | `build_graphsage()`, `mean_adjacency()`; torch imported lazily | called by `run_elliptic(extra=...)` |
| `backend/ringsentinel/elliptic/synthetic.py` | `write_synthetic_elliptic()` (SYNTHETIC) | tests and `run_stage08.py demo` |
| `scripts/run_stage08.py` | `verify`, `run`, `table`, `demo` | calls the package above |
| `scripts/secrets_scan.py` | scans working files and git history for key-shaped strings | tests; CI workflow audit.yml |
| `backend/app/main.py` (changed) | `client_address()`, rate-limit, body-size and security-header middleware | `backend/app/ratelimit.py` (`blocked`, `record`) |
| `.github/workflows/audit.yml` | weekly pip-audit, npm audit (production), secrets scan | CI |
| `requirements-gnn.txt` | optional PyTorch pin | owner |

### Stage 09 additions

| Path | What it does | Called by / calls |
| --- | --- | --- |
| `backend/app/audit_pg.py` | `PostgresAuditLog`: the audit store on Postgres (one connection per operation, advisory lock on append, `OperationalError` to `AuditUnavailable`) | built by `open_audit_log()` in `backend/app/audit.py`; uses `next_entry` and `verify_rows` from that module |
| `backend/app/audit.py` (changed) | `backend_of(url)`, `open_audit_log(url)`, `next_entry()`, `verify_rows()`, `AuditUnavailable` | `backend/app/main.py`, `backend/app/config.py`, `backend/app/audit_pg.py` |
| `backend/app/main.py` (changed) | `API_VERSION` "1.0.0"; handler turning `AuditUnavailable` into 503 + `Retry-After: 5` | uvicorn (`create_app`) |
| `backend/app/routes.py` (changed) | liveness route `GET /api/v1/live` (no database), `audit_backend` in `GET /api/v1/health` | Render health check, `scripts/smoke_deployed.py` |
| `frontend/src/components/CaseView.tsx` (changed) | the `isStandIn` helper: a cached answer from the offline stand-in provider is labelled "Offline stand-in, not a language model" | `AiCard` |
| `scripts/smoke_deployed.py` | `Checker` (injectable `fetch`), `check_api`, `check_web`, `main`; prints PASS/FAIL/WARN/SKIP and exits 1 on any FAIL | the owner after deploying; `.github/workflows/smoke.yml` |
| `scripts/sync_readme_results.py` | copies result tables from `docs/EVALUATION_RESULTS.md` and `docs/RESULTS_TABLE.md` into the README between the RESULTS markers | `scripts/reproduce.py`, tests |
| `requirements-api.txt` | slim runtime pins for the host | `render.yaml` |
| `render.yaml` | Render Blueprint (free web service, health check, env var names; secrets `sync: false`) | Render |
| `frontend/vercel.json` | security headers for the static site | Vercel |
| `.github/workflows/ci.yml` (changed), `.github/workflows/smoke.yml` | Postgres service job; manual smoke test | GitHub |
| `docs/DEPLOYMENT.md`, `docs/DIAGRAM_SPECS.md`, `docs/STAGE_09.md`, `RELEASE_NOTES_v1.0.0.md` | documentation | readers |


## 5. Runtime flows

Stage 01 pipeline (`python scripts/run_stage01.py`, `main()` in `scripts/run_stage01.py`):
1. `run_verify()` compares `data/raw` files with `data/raw/MANIFEST.json` using `verify_files()`.
2. `run_ingest()` calls `normalize()`: `read_transactions()` reads the CSV in chunks (all columns as text, ids kept as strings, sender and receiver sides share category sets, sorted by time) then `add_amount_inr()`; `parse_patterns()` reads the patterns file; `attach_labels()` matches pattern lines to rows and sets `is_illicit`, `ring_id`, `ring_type`; the label rate and unmatched share are checked; `validate_events()` runs; `build_rings_truth()` summarizes rings; files are written to `data/processed/hi_small/` [generated].
3. `run_split()` calls `build_split()`: cut times from row-count quantiles, `check_no_overlap()`, ring assignment by earliest event; writes the split table and metadata.
4. `run_baselines()` calls `prepare_baseline_frames()`, which returns only train and validation rows. It scores the velocity rule (`velocity_scores()`, threshold from validation), trains XGBoost on train with early stopping on validation (`train_xgb()`), evaluates both with `evaluate_scores()`, and writes `baseline_metrics.json` [generated].

Loading configuration: `get_settings()` reads `.env` then environment variables; blank values count as unset; unsupported variants raise a validation error.

Checking the docs: `main()` in `scripts/check_docs.py` calls `find_problems()`, which uses `extract_tokens()` and `check_token()`.

Inspecting raw files: `main()` in `scripts/inspect_schema.py` calls `inspect_csv()` and `inspect_patterns()`.

Stage 02 pipeline (`python scripts/run_stage02.py`, `main()` in `scripts/run_stage02.py`; needs the Stage 01 outputs):
1. `run_noise()`: unique accounts from the events go to `build_noise()` (account strings and seed only); writes `noise.parquet` and `noise_report.json` [generated], including `independence_report()` against ring accounts (reporting only).
2. `run_tune()`: `load_events()`, the validation window via `cumulative_events()`, `build_graph()` with a huge cap to get raw degrees, then `choose_hub_cap()` with the validation rings' accounts; writes `hub_cap_tuning.json` [generated].
3. `run_features()`: for each window, `effective_hub_cap()` (RS_HUB_CAP, else the tuned value, else 50), `build_window_features()`: `build_graph()` (IDF weights, hubs), `node_features()`, `detect_communities()`, `community_features()`, `attach_to_nodes()`; keeps the accounts active in the window's own split; writes `features.parquet`, `pruning_report.json` and `community_report.json` [generated]. Labels are read only for the reports and only for train and validation.
4. `run_ablation()`: four graph variants per window through `giant_component_rows()`; writes `ablation_giant_component.json` [generated].

Stage 03 pipeline (`python scripts/reproduce.py` or `main()` in `scripts/run_stage03.py`; needs Stage 01 and 02 outputs including `features.parquet` [generated]):
1. `load_prepared()` reads events and split into aligned numpy arrays (account codes, minutes, amounts, labels, ring ids) and calls `tabular_frame()` once for all events (velocity counts look only at earlier events).
2. `run_detect()`: `make_vault()` exposes train and validation rows only. `velocity` is the `sender_cnt_24h` column. `xgb_tabular` and `xgb_graph` each go through `_fit_and_score_xgb()`: `sample_rows()` keeps all positives and a share of negatives, `matrix_for()` builds the design matrix (graph variant joins each account's window features via `design_matrix()`), `fit_xgb()` trains with early stopping on a validation sample, `score_chunks()` scores every validation row, then `SplitVault.release_test()` hands out the test rows once. `ImputedIsolationForest` is fitted on a uniform train sample without labels. `write_scores()` writes `scores.parquet` [generated]; models go to the `models` folder.
3. `run_evaluate()`: `read_scores()` re-attaches scores (it refuses scores that do not match the events); for each detector `evaluate_detector()` picks the F1 threshold with `best_f1_threshold()` and the net-value threshold with `choose_nv_threshold()` over `candidate_thresholds()`, both on validation; `Scored.rings()` calls `extract_rings()` for each threshold; `ring_block()` applies `ring_metrics()` (Jaccard match) and `cost_terms()`; test is evaluated at the fixed thresholds; `cost_sweep()` repeats the net-value choice for 36 cost settings; `latency_block()` measures delay; `rings_payload()` writes `rings.json` [generated] with XGBoost contributions; `format_results_table()` writes `results_table.md` [generated].
4. `run_ablate()`: `build_uncontrolled_features()` rebuilds features with no degree cap and all edge weights 1, a third XGBoost is fitted on them, and `ablations.json` [generated] compares tabular only, hub control off, hub control on.
5. `run_robustness()`: for each dropout level a seeded share of the test-window transfers is removed, `build_window_features()` rebuilds the test-window features, and the saved `xgb_graph` model is applied with the validation thresholds from metrics.json [generated]; `robustness.json` [generated].
6. `scripts/reproduce.py` then calls `format_full_results()` and, if a previous metrics.json [generated] existed, `numeric_differences()` reports any change.

Stage 04 export (`python scripts\export_snapshots.py`, `main()` in `scripts/export_snapshots.py`; needs the Stage 03 outputs):
1. `export_snapshots()` calls `build_documents()`, which reads `rings.json` [generated], metrics.json [generated], `ablations.json` [generated], `robustness.json` [generated] and `latency.json` [generated], and hashes them.
2. Each ring gets `ring_id_for()` and `expected_value_inr()`; rings are sorted by value then id and cut to `--max-rings`.
3. `_edges_by_ring()` reads only the needed rows of `events.parquet` [generated] and aggregates each ring's listed transfers into account-to-account edges.
4. Placeholders are added for drift, replay and the AI block; each file is hashed in its canonical text form; `meta.json` [generated] gets the hashes and the `bundle_id`.
5. `write_bundle()` writes the six files; `load_bundle()` immediately re-validates what was written (schemas, hashes, queue and cases agree).

Serving a request (`python scripts\run_api.py`, `main()` in `scripts/run_api.py`): `create_app()` runs `load_app_settings()`, `SnapshotStore` (which calls `load_bundle()`, so a missing, edited or inconsistent bundle stops the start), `AuditLog`, adds the CORS and rate-limit middleware, and includes the router. A queue request: middleware `RateLimiter.check()`, then `queue()` in `backend/app/routes.py` merges the bundle's items with `AuditLog.statuses()`. A case request: `case()` returns the bundle's case plus `AuditLog.status_of()`.

Taking an analyst action: `take_action()` in `backend/app/routes.py` after `require_token()` and pydantic validation of `ActionRequest`: ring must exist in the bundle (404); `AuditLog.append()` opens `BEGIN IMMEDIATE`, looks up the idempotency key (same request returns the stored entry, different request raises `IdempotencyConflict`), checks `allowed_actions()` for the ring's current status (`InvalidTransition`), builds the entry with `prev_hash` of the last entry, computes `entry_hash()`, inserts, commits. `audit_verify()` calls `AuditLog.verify()`.

Loading a page in the browser (Stage 05): `AppShell` in `frontend/src/components/AppShell.tsx` creates the source (`createSource`, config from `readConfig` in `frontend/src/lib/config.ts`) and, for the header, asks for `meta` and `health`. A view calls `useResource`, which calls one source method:
1. If an API base URL is configured, `getJson` (`frontend/src/lib/http.ts`) asks the API with a timeout. Success: origin "api".
2. Any API failure (unreachable, timeout, non-2xx) falls through; a `SchemaVersionError` stops everything. For cases, a 404 from the live API is returned as an answer.
3. Next it fetches the file from /snapshots/ (origin "snapshot"), then from /demo-snapshots/ (origin "demo"). The cases.json file is fetched once and cached.
4. If nothing answers, `DataUnavailableError` lists every cause and the view shows `ErrorState` with a retry.
5. The view renders the data, and `OriginNote` says when it is not live.

Showing a case: `CaseView` loads the case; `ForceGraph` calls `capGraph` (keeps the 500 accounts with the largest transfer volume) then `layoutGraph` (d3-force to completion, then view fitted to the drawing).

Audit page: `AuditView` calls the open verify endpoint through `useResource`; the list is requested only after the user enters the analyst token (sent as the X-Analyst-Token header; kept in memory, and in sessionStorage only if the user ticks the box).

Making the demo or real bundle available: `python scripts\make_demo_bundle.py` rebuilds `frontend/public/demo-snapshots`; `python scripts\sync_frontend_snapshots.py` runs `load_bundle()` on `data/snapshots/` [generated] and copies the six files to `frontend/public/snapshots` [generated].

Case generation by a language model (Stage 06): `run_ai()` in `backend/ringsentinel/stage06.py` loads the bundle, calls `build_ai_cases()` (per ring `explain_case()`: cache, then the investigator and devil's advocate loops, then `verify()`, else `template_case_file()`) and merges the blocks into `cases.json` [generated] with `merge_ai_into_bundle()`.

Taking a decision in the browser (Stage 07): `ActionPanel` (`frontend/src/components/ActionPanel.tsx`) shows only the buttons `allowedActions` permits for the case's status (pending: confirm, dismiss, hold; held: confirm, dismiss; decided: none) and keeps them off until a name and a token of at least 16 characters are entered. A click calls `source.act()` (`createSource` in `frontend/src/lib/source.ts`), which sends `postJson` with the `X-Analyst-Token` header and a key from `newIdempotencyKey`. The same key is reused when the identical decision is retried after a network failure, so a decision that reached the server is not recorded twice (the server answers with `replayed: true`). On success `CaseView` calls `refresh`, which reloads the case without hiding the page, so the confirmation message stays. Status codes 401, 503, 409, 422, 429, 404 and network failure each get a plain-language message.

Live queue and feedback (Stage 07): `GET /queue` calls `_annotated()` in `backend/app/routes.py`: `AuditLog.statuses()` gives the latest status per ring, `annotate()` in `backend/ringsentinel/review/feedback.py` counts confirmed and dismissed rings in the bundle (`count_decisions`), computes the log-odds shift (`threshold_offset`), the shifted threshold (`effective_threshold`) and, per ring, the adjusted score and adjusted expected value (`expected_value_inr` on the adjusted score). Open rings above the shifted threshold with a positive adjusted value get a `live_rank`; others follow; decided rings come last. `order=export` restores the bundle's own order. Nothing is stored: the shift is recomputed from the audit log on every request. `GET /feedback` returns the same state alone.

Drift and replay build (Stage 07): `export_snapshots()` calls `build_documents(..., with_monitor=True)`. `build_drift_document()` reads `scores.parquet` [generated] (validation scores are the reference, test scores the monitored data) and `events.parquet` [generated] (timestamps and labels) and calls `compute_drift()`: `reference_bins()` cuts the reference at quantiles, `window_edges()` makes equal-width time windows with exact integer edges, `psi_from_shares()` scores each window, `classify()` labels it ok, warn, alert or insufficient (fewer than `RS_DRIFT_MIN_EVENTS` events). `build_replay_document()` takes the exported rings' transfers and calls `compute_replay()`: `ring_timing()` walks each ring's transfers in time order and records when they first touch `RS_RING_MIN_SIZE` accounts. If scores or events are missing the placeholders from `not_built()` stay and the bundle is still valid.

Replay in the browser: `ReplayView` holds one number, the cursor step. `detectedBy` lists the rings whose detection time is at or before the end of that step (`stepEndMs`), `eventsBy` counts the test transfers seen. Everything is a pure function of `replay.json` [generated], so the same file always replays the same way.

### Stage 08: Elliptic run (`python scripts\run_stage08.py run`)

1. `load_elliptic_settings()` reads `RS_ELLIPTIC_*`.
2. `load_elliptic()` reads the three CSV files and `assemble()` validates ids, steps and classes, counts dangling and cross-step edges.
3. `split_nodes()` assigns train, validation and test by time step.
4. `window_frames()` builds hub-controlled graph features for three cumulative windows through `build_window_features()`.
5. `fit_detector()` fits on labelled training rows; `evaluate_detector()` picks the F1 threshold on validation and calls `SplitVault.release_test()` once.
6. Per-step PSI against validation scores is computed in `_step_blocks()`.
7. metrics.json, scores.parquet, results.md are written under `data/processed/elliptic` [generated].

API requests in Stage 08: `rate_limit` middleware (client from `client_address()`; `authfail` bucket checked first) -> `limit_body_size` -> `security_headers`.

### Stage 09: deployed request path

1. The browser loads the static site from Vercel. The `createSource` function in `frontend/src/lib/source.ts` tries `NEXT_PUBLIC_API_BASE_URL` within `NEXT_PUBLIC_API_TIMEOUT_MS`; on failure it reads `frontend/public/snapshots`, then `frontend/public/demo-snapshots`.
2. Render's health probe calls the liveness route only; Neon is not woken by probes.
3. A decision: the frontend POSTs to the action route; the route in `backend/app/routes.py` checks the token, then appends to the audit store. For Postgres, the `append` method of `PostgresAuditLog` opens a connection, takes `pg_advisory_xact_lock(ADVISORY_LOCK_KEY)`, reads the last entry, builds the next one with `next_entry()` and inserts it. If Postgres cannot be reached the store raises `AuditUnavailable`; `backend/app/main.py` answers 503 with `Retry-After: 5`. Routes that need only the bundle keep answering.
4. `scripts/smoke_deployed.py` exercises steps 1 to 3 from outside.


## 6. Data contracts

D1 `data/raw/MANIFEST.json`: `{"schema_version": 1, "datasets": {<variant>: {"files": {<name>: {"size_bytes": int, "sha256": str}}}}}`.

D2 `data/processed/<variant>/events.parquet` [generated], sorted by (ts, original order):

| Column | Type | Meaning |
| --- | --- | --- |
| event_id | int64 | 0-based row position in the raw CSV |
| ts | datetime64[ns] | Dataset-local time, minute resolution |
| src_bank, dst_bank | category | Bank ids as text (shared categories) |
| src_account, dst_account | category | Account ids as text (shared categories) |
| amount_received, amount_paid | float64 | In the receiving / payment currency |
| recv_currency, pay_currency | category | Shared categories |
| payment_format | category | Seven values |
| amount_inr | float64 | amount_paid times a placeholder INR rate |
| ring_id | Int32 (nullable) | 1-based pattern block number, null when not in any pattern |
| ring_type | category | Pattern type, null when not in any pattern |
| is_illicit | int8 | The CSV `Is Laundering` label; falls back to "matched a pattern line" only for an old 10-column file |

`rings_truth.parquet` [generated]: ring_id, ring_type, ring_detail, n_pattern_lines, n_matched_events, n_accounts, first_ts, last_ts, and ring_split after the split step. `ingest_report.json` [generated]: variant, checks, label summary, ring counts, data profile (events per day, self-loops, accounts seen with more than one bank).

D4 `split.parquet` [generated]: event_id, split (train, val, test). `split_meta.json` [generated]: cut times, row and illicit counts per split, rings per split.

`baseline_metrics.json` [generated]: per detector n, positives, prevalence, pr_auc, threshold, tuned_on_this_split, precision, recall, f1, flagged, tp, fp, fn.

D3 `noise.parquet` [generated]: account (str, unique), derived_ip_id, derived_device_id, derived_vpa_handle_id (int64; ids below 1,000 are hubs, 1,000 to 99,999,999 small groups, above that unique). Synthetic. `noise_report.json` [generated]: counts, distinct values and the largest group per attribute, and the independence test (two-proportion z per attribute; `min_p_value`).

D5 `hub_cap_tuning.json` [generated]: `chosen_cap`, `rule`, `fallback_to_largest`, `table` of (cap, hub_nodes, ring_account_retention). `pruning_report.json` [generated]: `hub_cap` and, per window, accounts, accounts_with_transfer_edges, undirected_edges, hub_nodes_dropped, edges_dropped, share_edges_dropped, weights, top_dropped_hubs, and for train and validation ring_accounts_in_window and ring_accounts_dropped_as_hubs. `community_report.json` [generated]: per window components, giant component size and fractions, community counts and size percentiles, oversized counts, and for train and validation `ring_recovery_diagnostic` (reporting only). `ablation_giant_component.json` [generated]: rows of window, variant, components, giant size and fraction, hubs and attribute values dropped.

D6 `features.parquet` [generated]: one row per (window, account) for accounts active in that window's own split. Columns: window (train, val, test), account, community_id (-1 for hubs), then the node columns (out_cnt, in_cnt, self_cnt, out_amt, in_amt, out_deg, in_deg, degree, fan_ratio, flow_ratio, recip_partners, span_hours, active_hours, burst_share, txn_per_active_hour, hub_neighbor_share, mean_neighbor_log_degree, is_hub, kept_degree, idf_weighted_degree, triangles, cycles3, pagerank) and the community columns (all prefixed comm_). Float32 except counts; NaN in every controlled-graph column for hub accounts. No label, ring or split column.

D7 `scores.parquet` [generated]: one row per validation and test transfer. Columns: event_id (int64), split ("val" or "test"), then one float32 column per detector (`velocity`, `xgb_tabular`, `xgb_graph`, `iforest`); higher means more suspicious. `scores_ablation.parquet` [generated] has the same layout for `xgb_tabular`, `xgb_graph_nohub`, `xgb_graph`. `features_nohub.parquet` [generated] has the same layout as `features.parquet` [generated]. Models [generated], in the `models` folder next to the other processed files: xgb_tabular.json, xgb_graph.json, a matching name list (*.features.json) for each, and iforest.joblib. `detect_report.json` [generated]: per detector fit information, top features by gain, `val_pr_auc`, and `stage01_reference` (the Stage 01 `baseline_metrics.json` [generated] if present).

D8 `rings.json` [generated]: `{detector: "xgb_graph", split: "test", threshold, threshold_kind, rings: [...]}`. Each ring: ring_index, score (mean score of its transfers), n_members, n_transfers, amount_inr, oversized, members (up to 500 account strings), event_ids (up to 500), top_features (five items of feature and mean_contribution). If the validation net-value rule chose to flag nothing, `rings` is empty and `note` says why. Non-finite thresholds are written as the strings "inf" and "-inf".

D9 metrics.json [generated]: `meta` (variant, seed, hub cap, cost assumptions, tau, row and positive counts, protocol and scope notes), `detectors` (per detector: `val` and `test` with pr_auc, positives, prevalence and `at_f1_threshold` counts and rates including recall on ring positives and on unringed positives; `thresholds` f1 and net_value; `operating_points` f1 and net_value, each with `val` and `test` ring blocks holding predicted_rings, truth_rings, by_tau matched/precision/recall/f1, lenient_precision, ring_size, oversized_rings, cost_terms and net_value_inr; `val_net_value_choice`; test `ring_pr_tau_0.5` points and `ring_ap_grid`), and `cost_sweep` (per detector, 36 rows of capture, review cost, false-positive cost, chosen threshold, test net value and ring counts). `ablations.json` [generated]: `variants` keyed by detector name with label and summary metrics. `robustness.json` [generated]: `levels` with dropout, events_kept, test_pr_auc, at_val_f1_threshold, rings_at_f1_threshold, rings_at_nv_threshold, pr_auc_relative_to_no_dropout. `latency.json` [generated]: per detector threshold, rings with a flagged transfer, events and minutes median and 90th percentile. `results_table.md` [generated]: the comparison table. `docs/EVALUATION_RESULTS.md` [generated]: all tables for the docs.

D12 `data/snapshots/` [generated] (the bundle; the formal JSON Schemas are in `backend/ringsentinel/snapshots/schemas.py`). Every file has `schema_version` "1" except `meta.json` [generated], which also has it. Files are canonical JSON: sorted keys, two-space indent, UTF-8, LF, final newline, NaN written as null.
- `queue.json` [generated]: detector, split, threshold, threshold_kind, `score_calibrated` (always false), `value_formula`, `cost_assumptions` (review_cost_inr, fp_cost_inr, loss_capture_rate), optional `note`, and `items`: ring_id (`R-` plus 12 hex), rank (1..n), score, expected_value_inr, n_members, n_transfers, amount_inr, oversized, top_features (three of feature and mean_contribution).
- cases.json [generated]: `cases` keyed by ring_id; each has the queue fields plus members (sorted, up to 500), members_truncated, top_features (five), edges (src, dst, n_transfers, total_inr, first_ts, last_ts; up to 500), edges_available, edges_truncated, and `ai` (status "not_built", built_in_stage "06", investigator, verifier and benign_explanation null).
- metrics.json [generated]: meta, detectors, cost_sweep (as in D9), ablations, robustness, latency, results_table_md.
- `drift.json` [generated] and `replay.json` [generated]: see D11 below. When the inputs are missing they are `status: "not_built"` placeholders (`built_in_stage` "07", empty `windows` or `events`).
- `meta.json` [generated]: bundle_id, dataset_variant, seed, git_commit, evaluation_frozen, detector, split, n_rings_total, n_rings_exported, max_rings, `sources` (SHA-256 of each Stage 03 input) and `files` (SHA-256 of each of the five data files). `bundle_id` is the SHA-256 of the sorted "name:hash" lines of `files`; the git commit and the frozen flag do not change it.

D13 audit log, table `audit` in the SQLite file named by `RS_AUDIT_DB_URL`: seq (1, 2, ... without gaps), ts (UTC, microseconds, Z), ring_id, action (confirm, dismiss, hold), analyst, note, idempotency_key (unique), request_sha256 (hash of ring, action, analyst, note), prev_hash (64 zeros for seq 1), hash. `hash` is the SHA-256 of the canonical JSON of all other columns except itself. The API never returns `request_sha256`.

Frontend reading of D12 (Stage 05): the TypeScript types in `frontend/src/lib/types.ts` mirror the schemas; the app accepts only `schema_version` "1". The queue from a snapshot has no `status` field (the API adds it). metrics.json inner keys are read by `frontend/src/lib/metricsView.ts` tolerantly (see section 10).

D10 `data/processed/<variant>/ai_cases.json` [generated]: `{"schema_version": "1", "prompt_version": str, "cases": {<ring_id>: <ai block>}}`. AI block: status (not_built|ready), built_in_stage "06", source (llm|cache|template), input_hash (SHA-256 of ring facts plus prompt version), prompt_version, provider {name, model}, investigator (`CaseFile` with real account ids), verifier {status verified|unverified, issues[], warnings[], checked, attempts}, benign_explanation (`BenignCase` or null), benign_verifier, contested (bool), contested_reason, trace {tool names and counts}, fallback_kind (no_provider|outside_limit|provider_error|no_valid_output|null), fallback_reason. `data/processed/<variant>/ai_report.json` [generated]: by_source, verified_share_of_llm_attempted (null when no LLM case), contested, fallbacks, provider, model, merge {applied, stale, missing}, bundle ids. Inside the bundle the same block is the `ai` field of each case in cases.json [generated]; `meta.json` [generated] gains `sources["ai_cases.json"]`.

D11 (Stage 07) is the pair `drift.json` [generated] and `replay.json` [generated] inside the bundle, same `schema_version` "1" (optional fields were added; the Stage 04 placeholders stay valid).
- `drift.json` [generated], `status: "ready"`: detector, threshold, `psi_warn_level`, `psi_alert_level`, `reference` ({split "val", n_events}), `bins` ({n_bins, inner_edges, method, epsilon}), `windows` (index, start_ts, end_ts, n_events, psi or null, level ok|warn|alert|insufficient, mean_score, n_positives, n_flagged, flagged_rate, precision_at_threshold, recall_at_threshold), `summary` (n_windows, n_scored, n_alert, n_warn, alert_windows, max_psi, first_alert_index, test_psi, n_reference, n_test) and `notes`. PSI = sum over bins of (test share - reference share) times ln(test share / reference share), with shares floored at 1e-4.
- `replay.json` [generated], `status: "ready"`: detector, threshold, min_ring_members, `timeline` (start_ts, end_ts, n_steps, step_minutes and three equal-length integer arrays: events, ring_transfers, detected), `events` (per exported ring: ring_id, rank, score, expected_value_inr, n_members, n_transfers, first_ts, detected_ts, partial, assembly_minutes, assembly_events and, only when one true ring supplies at least half of the ring's transfers, truth_ring_id, truth_share, truth_first_ts, latency_minutes, latency_events), `summary` (medians and 90th percentiles of assembly and latency, n_rings, n_partial, n_with_truth, n_test_events) and `notes`. Retrospective: the scores use window-level features, so latencies are a lower bound.
- API additions (not bundle files): `GET /queue` items gain `status` and `live` (adjusted_score, adjusted_expected_value_inr, above_threshold, live_rank), and the response gains `order` and `feedback`; `GET /feedback` returns base_threshold, effective_threshold, offset_logit, max_offset_logit, step_logit, confirm_weight, at_bound, the counts, `rule`, `validated` (always false) and `note`.

### Stage 08 (Elliptic)

- Input elliptic_txs_features.csv: no header, 167 columns (txId, step, 165 features); VERIFY. elliptic_txs_classes.csv: `txId`, `class`. elliptic_txs_edgelist.csv: `txId1`, `txId2`.
- `metrics.json` [generated] under data/processed/elliptic: `meta` (split steps, counts, `not_applicable`), `detectors.<name>` with `threshold`, `test` metrics, `per_step` list (F1, PR-AUC, PSI, status).
- `scores.parquet` [generated]: txId, step, split, label, one score column per detector.
- `docs/RESULTS_TABLE.md` [generated]: two-dataset table; IBM cells say "not run" until Stage 03 output exists.

### Stage 09

D13 on Postgres: table `audit` with the same columns as the SQLite table (seq BIGINT primary key, ts, ring_id, action, analyst, note, idempotency_key UNIQUE, request_sha256, prev_hash, hash) plus index `audit_ring_seq`; the hash-chain definition is unchanged, so a log can be verified by either store's `verify()`. `GET /api/v1/health` gains `audit_backend` ("sqlite" or "postgres"). `GET /api/v1/live` returns `{"status": "ok"}`. Unreachable audit store: 503 with a `Retry-After` header.


## 7. Configuration

| Variable | Default | If wrong |
| --- | --- | --- |
| `RS_DATASET_VARIANT` | HI-Small | Unsupported value raises a validation error; file names are derived from it, so missing files are reported by the verify step |
| `RS_DATA_DIR` | `<repo>/data` | Pipeline reads and writes in the wrong place |
| `RS_SEED` | 42 | Non-integer raises ValueError; changes seeded results |
| `RS_TRAIN_FRAC`, `RS_VAL_FRAC` | 0.6, 0.2 | Must be in (0,1) and sum below 1, else a validation error |
| `RS_HUB_CAP` | blank (use tuned value; fallback 50) | Below 2 is rejected. Too low drops ring accounts, too high leaves hubs in the graph |
| `RS_ATTR_CAP` | 50 | Cap for derived attributes in the ablation only. Below 2 is rejected |
| `RS_COMMUNITY_CAP` | 200 | Components above this are split with Louvain. Below 2 is rejected |
| `RS_LOUVAIN_RESOLUTION` | 1.0 | Must be positive. Higher gives smaller communities |
| `RS_NEG_SAMPLE_FRAC` | 0.2 | Share of negative rows kept when fitting XGBoost; outside (0,1] is rejected. Lower is faster and less memory; scoring is unaffected |
| `RS_REVIEW_COST_INR`, `RS_FP_COST_INR` | 250, 500 | Cost model inputs (planning assumptions). Negative is rejected. They move the net-value threshold, not the F1 threshold |
| `RS_LOSS_CAPTURE_RATE` | 1.0 | Share of a caught ring's illicit volume that counts as saved; in (0,1]. At 1.0 the net-value rule can drift toward flagging everything with a hit |
| `RS_RING_TAU` | 0.5 | Jaccard needed for a ring-level true positive; 0.3 and 0.7 are always reported too |
| `RS_RING_MIN_SIZE` | 3 | Predicted rings with fewer accounts are dropped; below 2 is rejected |

Stage 04 (API and snapshots):

| Variable | Default | If wrong |
| --- | --- | --- |
| `RS_GIT_COMMIT` | blank (recorded as "unknown") | Only a label inside `meta.json` [generated]; `--git-commit` overrides it |
| `RS_SNAPSHOT_DIR` | `<data dir>/snapshots` | The API refuses to start ("snapshot folder not found") |
| `RS_ANALYST_TOKEN` | blank (actions disabled) | Under 16 characters raises a validation error at start. Blank means POST action and GET audit answer 503. A wrong header value gives 401 |
| `RS_AUDIT_DB_URL` | `sqlite:///<data dir>/audit/audit.sqlite3` | Anything except `sqlite:///...` raises a ValueError naming the variable. Pointing at a different file starts a new, empty log |
| `RS_CORS_ORIGINS` | `http://localhost:3000` | A browser front end on another origin is blocked; `*` is rejected |
| `RS_RATE_LIMIT_READ_PER_MIN`, `RS_RATE_LIMIT_WRITE_PER_MIN` | 120, 20 | Negative is rejected; 0 turns the limit off; too low gives 429 for normal use |

| `RS_LLM_PROVIDER` | none | Not one of none, fake, groq, gemini: validation error. `none` gives template case files only |
| `RS_LLM_MODEL` | provider default | Wrong name gives provider errors (HTTP 404/400); every ring then falls back to a template (`provider_error`) |
| `RS_LLM_TIMEOUT_S`, `RS_LLM_MIN_INTERVAL_S` | 60, 2.5 | Timeout must be positive; interval too low gives 429 from free tiers (retried, then fallback) |
| `RS_LLM_MAX_TOOL_CALLS`, `RS_LLM_VERIFY_RETRIES` | 5, 2 | Ranges 0 to 10 and 0 to 5 else validation error; too low gives thin or unverified answers |
| `RS_AI_MAX_LLM_CASES` | 100 | Rings past the limit get templates (`outside_limit`) |
| `RS_FEEDBACK_STEP`, `RS_FEEDBACK_MAX_OFFSET`, `RS_FEEDBACK_CONFIRM_WEIGHT` | 0.1, 1.5, 1.0 | Read by the API (`load_app_settings()`). Hard ceilings 1.0, 3.0 and 5.0, and negative, non-numeric or NaN values are refused at start, so a typo cannot widen the bound. Too high a step makes a few dismissals raise the threshold at once |
| `RS_PSI_WARN_LEVEL`, `RS_PSI_ALERT_LEVEL` | 0.10, 0.25 | Need 0 < warn < alert. Read when the bundle is exported; changing them needs a re-export |
| `RS_DRIFT_WINDOWS`, `RS_DRIFT_BINS`, `RS_DRIFT_MIN_EVENTS` | 8, 10, 500 | Ranges 2 to 60, 3 to 50, at least 1. Too few events per window gives "insufficient" instead of a PSI |
| `RS_REPLAY_STEPS` | 96 | Range 10 to 500; the resolution of the replay slider |
| `GROQ_API_KEY`, `GEMINI_API_KEY` | blank | Read from the environment (or `.env` loaded into it) by `make_provider()`; missing key is a clear error naming the variable; never stored in Settings |

Stage 05 (frontend, read at build time and baked into the browser files, so never put a secret in them; set in `frontend/.env.local` [generated], names in `frontend/.env.example`):

| Variable | Default | If wrong |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | blank (snapshot-only mode) | A wrong URL means every API call fails and the UI quietly falls back to the snapshot, with a "Backend unreachable" note. A browser origin not listed in `RS_CORS_ORIGINS` is blocked and looks the same. Changing it needs a restart or rebuild |
| `NEXT_PUBLIC_API_TIMEOUT_MS` | 4000 | Values outside 200 to 60000 are ignored. Too low makes a slow, waking backend look down; too high delays the fallback |

Reserved for later stages and listed in `.env.example`: Kaggle credentials. `config/fx_rates_inr.json` holds the placeholder currency rates; a currency missing from it stops ingest.

### Stage 08

| Variable | Default | If wrong |
| --- | --- | --- |
| `RS_ELLIPTIC_DIR` | `<data>/raw/elliptic` | `verify` reports missing files |
| `RS_ELLIPTIC_TRAIN_LAST_STEP` / `RS_ELLIPTIC_VAL_LAST_STEP` | 29 / 34 | validation error unless 1 <= train < val < 49 |
| `RS_ELLIPTIC_HUB_CAP` | `RS_HUB_CAP` else 50 | must be >= 2 |
| `RS_RATE_LIMIT_AUTHFAIL_PER_MIN` | 10 | 0 disables the lockout |
| `RS_TRUSTED_PROXY_HOPS` | 0 | too high: forged `X-Forwarded-For` trusted; too low behind a proxy: all clients share one address |
| `RS_MAX_BODY_BYTES` | 16384 | 1024 to 1000000 |
| `RS_API_DOCS` | on | `0` or `off` removes the interactive docs |

### Stage 09

- `RS_AUDIT_DB_URL`: now also `postgresql://USER:PASSWORD@HOST/DB?sslmode=require` (or `postgres://`). Any other scheme fails at start with an error that does not echo the URL. A wrong password or host does not fail at start: it surfaces as 503 on the first audit call (smoke check "audit chain verifies").
- `RS_TRUSTED_PROXY_HOPS`: `render.yaml` sets 2 (unverified). Too low: all clients behind the proxy share one rate-limit bucket. Too high: falls back to the socket peer.
- `RS_API_DOCS`: `render.yaml` sets 0 (the smoke script checks it with `--expect-docs-off`).
- `RS_CORS_ORIGINS`: must equal the Vercel address exactly (smoke check "CORS allows the frontend origin").
- `RS_TEST_POSTGRES_URL`: tests only; the database name must contain "test" and its `audit` table is dropped.
- `PYTHON_VERSION` (Render): a fully qualified version such as 3.13.5.
- `NEXT_PUBLIC_API_BASE_URL`: baked into the frontend at build time; change it and the site must be rebuilt (smoke check "frontend build points at this API").


## 8. Test map

| Test file | Guards | Failure signals |
| --- | --- | --- |
| `backend/tests/test_smoke.py` | Imports, version | Broken install or `pythonpath` |
| `backend/tests/test_config.py` | Variant switch, per-variant paths, split fractions | Small and Medium outputs could collide; bad config accepted |
| `backend/tests/test_check_docs.py` | Docs checker and this repo's docs | A doc names something that does not exist |
| `backend/tests/test_inspect_schema.py` | Schema inspector | Misleading schema review |
| `backend/tests/test_schema_manifest.py` | Header check, checksum manifest | Wrong file or tampered download goes unnoticed |
| `backend/tests/test_patterns.py` | Patterns parser on real excerpts, malformed input | Rings mislabelled or parse errors hidden |
| `backend/tests/test_normalize.py` | Id types, chunk independence, labels matched exactly once (duplicates, large amounts), validation, end-to-end ingest | Silent mislabelling, float-parsing mismatches, unsorted or null data |
| `backend/tests/test_split_metrics.py` | No time overlap, ties, ring assignment; metric hand cases and sklearn cross-check | Leakage across splits, wrong metrics |
| `backend/tests/test_baselines_stage01.py` | Trailing counts (hand and brute force), no future information, test rows excluded, deterministic baselines, manifest step | Leakage, nondeterminism |
| `backend/tests/test_real_data.py` | Real header, manifest match, 370 blocks and 3,209 lines | Real files differ from what the code expects. Skipped when the files are absent |
| `backend/tests/test_label_note.py` | The baseline metrics note names the real label source | Results file describing labels wrongly |
| `backend/tests/test_hubs.py` | IDF values, hub cap boundary, cap selection and its fallback, cap precedence | Wrong weights or wrong cap chosen |
| `backend/tests/test_graph_build.py` | Toy graph: degrees, pairs, self-transfers, weights, components with and without control, pruning report, past-only windows | Graph or hub control wrong; leakage across windows |
| `backend/tests/test_communities.py` | Louvain split of joined cliques, oversized flag, hubs, determinism | Communities wrong or unstable |
| `backend/tests/test_noise.py` | Determinism, order independence, sharing structure, no label access, independence test and its power | Noise layer leaking label information |
| `backend/tests/test_features.py` | Hand-checked features, hub rows NaN, burstiness, PageRank, determinism, label columns ignored, post-boundary events ignored | Feature errors, leakage |
| `backend/tests/test_ablation.py` | Giant component with and without hub control and derived attributes on a toy graph | Ablation misreports |
| `backend/tests/test_stage02_pipeline.py` | Stage 02 end to end on the synthetic data: outputs, shapes, nulls, reproducibility, test labels not read | Orchestration broken |
| `backend/tests/test_stage03_metrics.py` | PR-AUC hand cases and scikit-learn cross-check with ties, precision/recall/F1, best-F1 threshold | Wrong metric or threshold |
| `backend/tests/test_stage03_rings.py` | Ring extraction (components, self-transfers, Louvain split, determinism), Jaccard boundary, one-to-one matching | Rings or ring metrics wrong |
| `backend/tests/test_stage03_cost.py` | Cost-term and net-value arithmetic, threshold choice, flag-nothing rule, threshold grid | Wrong rupee figures or thresholds |
| `backend/tests/test_stage03_detect.py` | Trailing counts against brute force, no future information, sampling, design matrix, test-split vault, XGBoost and Isolation Forest behaviour | Leakage, wrong features, protocol breach |
| `backend/tests/test_config_stage03.py` | Stage 03 defaults, env overrides, validation, paths | Bad settings accepted |
| `backend/tests/test_stage03_pipeline.py` | Stage 03 end to end on the synthetic data; thresholds chosen on validation only; test released once per detector; rewriting the test split leaves validation scores and model files unchanged (and rewriting validation does change them); reproducibility; robustness at 0 percent reproduces the main score; latency hand case | Orchestration broken, leakage, nondeterminism |

| `backend/tests/test_stage04_export.py` | Expected-value arithmetic, ranking, stable ring ids, byte-identical exports (also from a copy of the inputs), bundle id, max rings, edge aggregation, truncation flags, placeholders, empty bundle, canonical form, and the loader refusing missing, edited, invalid or inconsistent bundles | Wrong queue order or numbers, non-deterministic export, a tampered bundle being served |
| `backend/tests/test_stage04_audit.py` | Chain and genesis, hash covers every field, tamper cases (edit, forged entry, overwritten hash, middle or first deletion, tail truncation limit), status and transition rules, idempotent replay and conflict, rollback after a refusal, 12 concurrent identical requests, persistence, URL parsing | Undetected tampering, double writes, broken chain |
| `backend/tests/test_stage04_api.py` | Every endpoint's contract, paging and bounds, auth (401, 503), validation (15 bad bodies), repeated submission, conflicts, SQL-looking input, audit list and verify (including tampering through the database file), rate limits with a fake clock, CORS, start-up refusal on a bad bundle | API behaviour drifting from the documented contract |
| `backend/tests/test_stage04_config.py` | API settings defaults and overrides, blank values, weak token, wildcard CORS, token hidden in repr, rate-limiter window, isolation and memory bound | Bad configuration accepted; limiter wrong |
| `backend/tests/test_stage06_facts_tools.py` | Aliasing, recomputed numbers, coverage, cycle detection, each tool's output and bounds | Wrong facts reaching the verifier or the prompt |
| `backend/tests/test_stage06_verifier.py` | Planted fake aliases, ids, counts, amounts, dates and numbers are rejected; true claims pass; tolerances | A fabricated fact being accepted |
| `backend/tests/test_stage06_agent.py` | Tool loop, budget, malformed replies, verify-and-retry, devil's advocate, contested flag | Loop not terminating or accepting invalid output |
| `backend/tests/test_stage06_pipeline.py` | Cache hit when the provider fails, fallback kinds, circuit breaker, template always verified, honest summary | A provider outage breaking the queue; template counted as LLM |
| `backend/tests/test_stage06_query.py` | DSL accepts valid queries; unknown fields, operators, types, enum values rejected | Question text reaching code |
| `backend/tests/test_stage06_injection.py` | Instructions hidden in data or the question do not change behaviour; feature names sanitised | Prompt injection |
| `backend/tests/test_stage06_providers.py` | Groq and Gemini request shape through a fake transport, key only in headers and never in errors, retry and pacing | Key leak; bad retry |
| `backend/tests/test_stage06_bundle.py` | Merge touches only `ai`, queue bytes unchanged, scores unchanged, re-export keeps AI, stale blocks ignored, tamper refused, API serves the block, settings, both scripts | Model output altering anything it must not |
| `backend/tests/test_stage04_integration.py` | Synthetic world through Stage 02 and 03, export, API session with actions, audit verify, and both `scripts/export_snapshots.py` outcomes | The pieces working alone but not together |
| `frontend/tests/graph.test.ts` | Node building, the 500-account cap (count, ties, order independence, kept edges, the demo's oversized ring), deterministic layout that fits its view | A graph that freezes the browser or changes between visits |
| `frontend/tests/source.test.ts` | Config parsing; API, snapshot, demo fallback order; timeouts; schema-version refusal; 404 handling; cached cases; token header | Offline mode broken, stale data shown as live |
| `frontend/tests/pages.test.tsx` | Queue, case, metrics, audit and the app shell: loading, empty, error and offline states, filters, paging, case graph and cap, keyboard selection, metrics panels and missing-section messages, audit token flow and chain states, app shell with the backend unreachable, banners | The analyst experience breaking |
| `frontend/tests/lib.test.ts` | Formatting, markdown table parser, metrics extractors, chart colour mapping | Wrong figures on the dashboard |
| `frontend/tests/palette.test.ts` | WCAG AA contrast for text pairs, light-only | Unreadable text, a dark-mode rule sneaking in |
| `backend/tests/test_stage05_bundle.py` | The committed demo bundle passes `load_bundle()`, equals a fresh build, is deterministic, has an oversized ring, is marked DEMO; the sync script copies a valid bundle and refuses a tampered one | Demo bundle out of date or invalid; the sync script copying bad data |
| `backend/tests/test_stage07_feedback.py` | The feedback rule: bounds for every count, hard ceilings, confirmations never lower the threshold, holds neutral, live ordering, decided rings last, config validation | The threshold escaping its bounds; a changed rule going unnoticed |
| `backend/tests/test_stage07_drift.py` | PSI by hand, binning with ties, exact window edges, quiet on unshifted data, alert on shifted data, too-few-events windows, determinism | A drift alarm that fires on noise or stays silent on a real shift |
| `backend/tests/test_stage07_replay.py` | Detection time per ring, partial rings, truth latency only when one true ring dominates, timeline counts, determinism | A wrong detection time or a meaningless latency |
| `backend/tests/test_stage07_export.py` | The bundle with drift and replay: valid, deterministic bytes, bundle id covers both, placeholders when inputs are missing, tamper refused, AI merge keeps them | The exporter producing an invalid or non-reproducible bundle |
| `backend/tests/test_stage07_api.py` | Live queue and `GET /feedback` through the API, bounds after repeated dismissals, env parsing and ceilings, and the scripted scenario (open queue, open case, act, retry, audit entry, chain verify, replay, drift) | The API and the rule disagreeing; the plan's M7 scenario breaking |
| `frontend/tests/stage07.test.tsx` | Decision panel (enabling, success, retry key reuse, every error message, closed cases), live queue and feedback card, drift page (alert, warn, stable, not built, too few), replay page (steps, determinism, partial, not built), the scripted scenario in the UI | A decision button that does the wrong thing; a drift alert that is not shown |
| `frontend/tests/ai_card.test.tsx` | The Explanation card: verified, template, unverified and contested states; model text shown as plain text | AI text mislabelled or interpreted as markup |

Run: `pytest` from the repo root; `npm run check` from `frontend` for the frontend.

### Stage 08

| File | Guards | Failure signals |
| --- | --- | --- |
| `backend/tests/test_stage08_load.py` | loader, schema checks, split | changed file layout, bad ids, overlap between splits |
| `backend/tests/test_stage08_graph.py` | windows see no future edges, hub cap, allow-list | leakage or graph features changing meaning |
| `backend/tests/test_stage08_pipeline.py` | poisoned test period leaves fits unchanged, vault, PSI alert vs quiet, determinism | test-label leakage, threshold chosen on test |
| `backend/tests/test_stage08_gnn.py` | GraphSAGE determinism, no label access (skips without torch) | GNN changes |
| `backend/tests/test_stage08_hardening.py` | lockout, proxy address, body size, headers | API middleware regressions |
| `backend/tests/test_stage08_secrets_scan.py` | scanner rules, no value printed, history | scanner regressions |

### Stage 09

| Test file | Guards | Failure signals |
| --- | --- | --- |
| `backend/tests/test_stage09_audit_pg.py` | URL scheme handling, password never echoed, settings validation, factory, unreachable DB gives `AuditUnavailable`; with `RS_TEST_POSTGRES_URL`: same chain, idempotency, two concurrent writers, verify, tamper detection on Postgres | audit store regression |
| `backend/tests/test_stage09_api.py` | liveness works with a dead audit store, 503 + `Retry-After`, snapshot-only routes still 200, version | a route started touching the database, or error mapping broke |
| `backend/tests/test_stage09_smoke.py` | the smoke script passes a healthy deployment and fails each broken one (CORS, stale snapshot, edited snapshot, wrong API address, missing page, dead host, wrong token), never prints the token, write check is opt-in | smoke script regression |
| `backend/tests/test_stage09_readme_sync.py` | README tables equal the generated files; hand edits are caught; the real README matches | README drifted from results: run `python scripts\sync_readme_results.py` |
| `backend/tests/test_stage09_deploy.py` | `requirements-api.txt` pins equal `requirements.txt`; the API imports and serves with the modelling stack blocked; `render.yaml` has no secret; frontend snapshot copy equals the committed bundle; snapshots are not gitignored | a deploy file or a pin drifted |
| `frontend/tests/ai_card.test.tsx` (extended) | the offline stand-in is never called a language model | label regression |


## 9. Debugging playbook

| Symptom | Likely cause | Inspect | Confirm | Usual fix |
| --- | --- | --- | --- | --- |
| `ModuleNotFoundError: ringsentinel` | Not in the repo root, or running a script without the path hook | `pyproject.toml`; top of `scripts/run_stage01.py` | `pytest --collect-only` | Run from the repo root |
| "Raw file check FAILED" | Missing, renamed or different download | `data/raw/MANIFEST.json`, `run_verify()` | Compare names and sizes | Re-download; or `--write-manifest` if the change is intended |
| `SchemaError: Unexpected transactions header` | Different file version | `check_header()` in `backend/ringsentinel/ingest/schema.py` | `python scripts/inspect_schema.py` | Compare with `docs/DATA.md` |
| `ValidationError: ... copy of the receiver column` | The CSV's sender account column duplicates the receiver column (senders lost) | `check_sender_accounts()` | `python scripts\diagnose_matching.py`, first block | Obtain an intact transactions file; no code workaround |
| `ValidationError: could not be matched` | Patterns file and CSV differ in one or more fields (cause unknown until the diagnostic is read) | `attach_labels()`; `diagnose_matching()` | `python scripts\diagnose_matching.py`, then read the leave-one-field-out block | Depends on the field named; never loosen the check |
| `ValidationError: Illicit rate ... outside the expected range` | Labels did not attach | `check_label_rate()`, ingest report | Print `label_rate` | Check unmatched lines |
| `ValidationError: No INR rate` | A currency is missing from the rates file | `config/fx_rates_inr.json` | Error lists the currencies | Add the rate |
| `SplitError: ... empty` | Too many equal timestamps or tiny data | `compute_cuts()` | Check `ts` spread | Adjust fractions |
| `ValueError: No positive examples` | A split has no illicit rows | `split_meta.json` [generated] | See `illicit_rows` | Adjust fractions or variant |
| Memory error on ingest | Too little RAM (more likely on Medium) | `read_transactions()` | Task manager | Smaller chunk size, close other programs |
| pip install fails for a pinned package | No wheel for the owner's Python or OS | `requirements.txt` | Read the pip error | Report it; the pin is changed |
| Different results between runs | Seed or thread count changed | `RS_SEED`, `XGB_PARAMS`, `train_xgb()` | Compare `baseline_metrics.json` [generated] | Keep `n_jobs=1` and the seed |
| "Missing ... Run scripts\run_stage01.py first" | Stage 01 outputs absent | `main()` in `scripts/run_stage02.py` | Look in `data\processed\hi_small` | Run Stage 01 |
| Ablation says "Missing noise.parquet" | Noise step not run | `scripts/ablation_giant_component.py` | Check the file exists | `python scripts\run_stage02.py --step noise` |
| Too many accounts dropped as hubs or ring accounts missing from the graph | Hub cap too low | `choose_hub_cap()`, `pruning_report()` | Read `hub_cap_tuning.json` [generated] | Rerun `--step tune`, or set `RS_HUB_CAP` |
| Stage 02 features step very slow | Community splitting on a huge component with a slow Louvain | `_louvain_parts()` in `backend/ringsentinel/graph/communities.py` | Time `detect_communities()` | Keep igraph; do not swap in networkx Louvain (over five minutes on the real data) |
| `ValueError: noise table is missing accounts` | `noise.parquet` [generated] built from different events than the current ones | `attribute_links()` | Compare account counts | Rerun `--step noise` |
| "Missing ... features.parquet" from Stage 03 | Stage 02 not run | `check_inputs()` in `scripts/run_stage03.py` | Look in `data\processed\hi_small` | Run `scripts\run_stage02.py` |
| `ValueError: ... does not match the current events` | `scores.parquet` [generated] built from different events or split | `read_scores()` | Compare event counts | Rerun `--step detect` |
| `ValueError: The train split needs both positive and negative rows` | A split has no positives or no negatives | `fit_xgb()`, `split_meta.json` [generated] | See illicit rows per split | Adjust split fractions or variant |
| `TestSplitAccessError` | Code asked for the test split twice for one detector, or fitting code touched it | `SplitVault.release_test()` | Read the message for the detector name | Fix the caller; never bypass the vault |
| Net-value threshold says "flags nothing" or flags nearly everything | Costs too high for the model, or capture rate 1.0 with huge synthetic amounts | `choose_nv_threshold()`, `cost_sweep()` | Read `cost_sweep` in metrics.json [generated] | Report the sweep; do not tune costs to get a nicer answer |
| Very large rings or very slow evaluation | Threshold flags a huge share of transfers (tied scores, velocity rule) | `candidate_thresholds()`, `extract_rings()` | Check `flagged` and ring sizes in metrics.json [generated] | The grid already skips thresholds that flag over ten times the maximum; raise `RS_RING_MIN_SIZE` or lower the community cap only with a documented reason |
| `reproduce.py` exits with code 2 | New numbers differ from the previous metrics.json [generated] | `numeric_differences()` output | Compare platform, `RS_SEED`, package versions | Same machine and inputs should be identical; otherwise record the platform |
| Export fails with "Stage 03 output missing" | Stage 03 not run (or its outputs deleted) | `_read_json()` in `backend/ringsentinel/snapshots/export.py` | The message names the file | Run `scripts\run_stage03.py` |
| API start says "CANNOT START: ... hash mismatch" | A bundle file was edited or partly overwritten | `load_bundle()` in `backend/ringsentinel/snapshots/bundle.py` | The message names the files | Re-run `scripts\export_snapshots.py`; never edit bundle files by hand |
| API start says "violates its schema" | Bundle written by a different version of the exporter | `validate_document()`, `backend/ringsentinel/snapshots/schemas.py` | Message lists the first problems | Re-export with the current code |
| Two exports differ | An input file or option changed (commit label changes only `meta.json` [generated]) | `build_documents()` | Compare `sources` in both `meta.json` [generated] files | Rerun Stage 03 deterministically; check `RS_SEED` |
| 503 on action or audit list | `RS_ANALYST_TOKEN` not set | `require_token()` in `backend/app/routes.py` | the health endpoint shows `actions_enabled` | Set the token in `.env` and restart |
| 401 on action | Wrong or missing X-Analyst-Token header | `require_token()` | Compare the header with `.env` | Send the same value |
| 409 on action | Idempotency key reused for a different request, or the ring is already confirmed, dismissed or (for hold) held | `AuditLog.append()`, `allowed_actions()` | Read the `detail` text; the case endpoint shows the status | Use a fresh key; decided rings are closed by design |
| 422 on action | Body failed validation (extra field, bad key format, control character, long note) | `ActionRequest` in `backend/app/schemas.py` | The response lists the field | Fix the body |
| 429 | Rate limit hit | `RateLimiter.check()` | `Retry-After` header | Wait, or raise `RS_RATE_LIMIT_*` |
| The audit verify endpoint says ok is false | The audit database was edited outside the API, or restored from a different copy | `AuditLog.verify()` | `first_bad_seq` and `reason` in the response | Treat as tampering; restore from a trusted copy |
| Browser blocked by CORS | Front end origin not listed | `create_app()` | Browser console | Add the origin to `RS_CORS_ORIGINS` |
| `ValueError: RS_AUDIT_DB_URL must look like sqlite:///...` | Non-SQLite URL | `sqlite_path_from_url()` | Read the message | Use a sqlite URL until Stage 09 |
| Every ring shows source template, fallback `provider_error` | Missing or wrong key or model, quota, network | `make_provider()`, `ai_report.json` [generated] fallbacks | `python scripts\run_stage06.py --provider groq --limit 1` and read the message | Set the key in `.env`; check `RS_LLM_MODEL` |
| Verified share is low | Model rounds numbers or cites unseen ones | `verify()` issues in the case's `verifier` block | Open a case in cases.json [generated] | Tighten the prompt (bump `PROMPT_VERSION`); try another model |
| AI blocks vanished after export | Detector output changed, so `input_hash` is stale | `apply_ai_blocks()` | `ai_report.json` [generated] merge.stale | Rerun `scripts\run_stage06.py` |
| Query rejected with QueryError | Field, op or value outside the DSL | `parse_query()` | Read the message | Rephrase or pass `--dsl` |
| Feature values change after a rerun | Hub cap or community settings changed, or a different platform | `effective_hub_cap()`, `Settings` | Compare `hub_cap` in `pruning_report.json` [generated] | Fix the settings; features are deterministic for fixed settings |
| Page says "Could not load data" | No API and no snapshot answered (a static server not serving `public`, or wrong base path) | `createSource` in `frontend/src/lib/source.ts`; the causes are listed on the page | Open `/demo-snapshots/queue.json` in the browser | Serve `frontend/out` [generated] from its root, or run `npm run dev` |
| "Backend unreachable: using saved snapshot" with the API running | Wrong `NEXT_PUBLIC_API_BASE_URL`, CORS origin not allowed, or the value was set after the build | `frontend/src/lib/config.ts`; browser console | `curl http://127.0.0.1:8000/api/v1/health`; check the console for a CORS error | Fix the URL, add the origin to `RS_CORS_ORIGINS`, restart or rebuild the frontend |
| Yellow "Demo data" banner on real work | No real bundle in `frontend/public/snapshots` [generated] | `AppShell` | List the folder | `python scripts\sync_frontend_snapshots.py` |
| "Snapshot out of date" banner | The saved snapshot is a different bundle from the one the API serves | `AppShell` | Compare bundle ids (health endpoint, `meta.json` [generated]) | Re-run the sync script |
| "Unsupported snapshot schema_version" | Bundle from a newer exporter | `SchemaVersionError` in `frontend/src/lib/source.ts` | Read `schema_version` in the files | Update the frontend types and reader together |
| A metrics panel says "not in this bundle, or not a layout ... recognises" | The real Stage 03 key names differ from the documented ones, or the data is absent | `frontend/src/lib/metricsView.ts` (the matching extractor) | Open the raw document at the bottom of the page | Adjust the extractor and its test to the real layout |
| Case graph shows fewer accounts than the case lists | The 500-account cap, or the bundle truncated members or edges | `capGraph`; the graph summary line | Read the line above the graph | By design; use the link table |
| Decision buttons stay disabled | No name entered, or the token has fewer than 16 characters | `ActionPanel` (`formOk`) | Read the grey line under the buttons | Enter both |
| "The server refused this decision" (409) | The ring is already decided, or the idempotency key was reused for a different request | `allowed_actions()` in `backend/app/audit.py` | Open the case; its status chip | Reload the case; decided cases are closed by design |
| Queue "Live order" column shows "below threshold" for most rings | Many dismissals raised the threshold | `GET /feedback` (`offset_logit`, `effective_threshold`) | Compare with `base_threshold` | By design; switch the order to "As exported", or lower `RS_FEEDBACK_MAX_OFFSET` |
| Threshold stuck, "at the limit" chip | The shift reached `RS_FEEDBACK_MAX_OFFSET` | `threshold_offset()` in `backend/ringsentinel/review/feedback.py` | `GET /feedback`: `at_bound` | Confirm rings to cancel dismissals, or accept |
| Drift page says "not computed" | scores or events table was missing at export | `build_drift_document()`; `scripts/export_snapshots.py` prints `drift` and `replay` status | `python scripts\export_snapshots.py` output | Run Stage 03, then export again without `--no-monitor` |
| Every drift window is an alert on the synthetic or a small dataset | Test scores really differ from validation scores, or windows are small | `compute_drift()`; `notes` in `drift.json` [generated] | Window sizes (`n_events`), `reference.n_events` | Check `RS_DRIFT_WINDOWS` and `RS_DRIFT_MIN_EVENTS`; a real shift is a finding, not a bug |
| Replay latency column all "n/a" | No ring is dominated by one true ring (needs at least half of its transfers) | `compute_replay()` | `n_with_truth` in `replay.json` [generated] | By design; assembly time is still shown |
| Audit page empty with "needs the backend" | Snapshot-only mode | `AuditView` | Check `NEXT_PUBLIC_API_BASE_URL` | Set it and start the API |
| `npm install` or `npm ci` fails | Node older than 22.12, or a blocked registry | `frontend/package.json` (`engines`) | `node -v` | Install Node 22 LTS |

Order to rule out causes: environment (venv active, installs done), working directory, config values, input files (verify step), then code. Logs: pytest output, console output of `scripts/run_stage01.py`, and the ingest report.

### Stage 08

| Symptom | Likely cause | Inspect | Confirm | Usual fix |
| --- | --- | --- | --- | --- |
| `EllipticSchemaError` on load | real file differs from the expected layout | `backend/ringsentinel/elliptic/schema.py`, `read_features()` | `python scripts\run_stage08.py verify` | compare with the paper; update schema constants, mark VERIFY resolved |
| Test PR-AUC much lower than validation | late-step distribution shift | `per_step` PSI in metrics.json [generated] | `python scripts\run_stage08.py table` | expected; report it, do not tune on test |
| `GnnUnavailableError` | torch not installed | `torch_available()` | `python -c "import torch"` | `pip install -r requirements-gnn.txt` |
| API 429 after a few wrong tokens | `authfail` bucket full | `RS_RATE_LIMIT_AUTHFAIL_PER_MIN` | wait one minute | correct the token; raise limit if shared address |
| All users rate-limited together on a host | proxy hides client address | `RS_TRUSTED_PROXY_HOPS` | inspect `X-Forwarded-For` | set the hop count from the host docs |
| API 413 or 411 | body too large or chunked | `RS_MAX_BODY_BYTES`, `limit_body_size` | check request size | shorten the note field |

### Stage 09

| Symptom | Likely cause | File and function | Command to confirm | Usual fix |
| --- | --- | --- | --- | --- |
| Site read-only, banner says saved snapshot | API asleep, wrong `NEXT_PUBLIC_API_BASE_URL`, or CORS | `frontend/src/lib/source.ts` `createSource` | `python scripts\smoke_deployed.py --api URL --web URL --wait 120` | wait, then fix the variable named in the FAIL line |
| 503 on decisions | Neon waking, or bad `RS_AUDIT_DB_URL` | `backend/app/audit_pg.py` `_connect` | `GET /api/v1/health` (503 means the audit store) | retry; re-copy the connection string |
| Smoke: `frontend snapshot matches the API bundle` FAIL | frontend and API built from different bundles | `scripts/sync_frontend_snapshots.py` | smoke output shows both ids | sync, commit, push |
| Smoke: `snapshot files match the hashes in meta.json` FAIL | a snapshot file edited or half-copied | `data/snapshots/meta.json` `files` | smoke names the files | re-export and re-sync |
| `test_the_real_readme_matches_...` fails | results regenerated but README not synced | `scripts/sync_readme_results.py` | `python scripts\sync_readme_results.py --check` | run it without `--check`, commit |
| Render install fails | pin or Python version | `requirements-api.txt`, `PYTHON_VERSION` | Render build log | keep pins equal to `requirements.txt` |


## 10. Known issues and limits

- **Labels versus rings**: labels come from the CSV `Is Laundering` column (5,177 positives); only 3,209 are in a pattern ring (see `docs/DATA.md`).
- **Positive rate drifts upward** across the time split (0.075, 0.107, 0.177 percent for train, val, test).
- **Real-data status**: Stage 01 was run by the owner on the real corrected files. Stage 02 was run by the builder on the same files (taken from the owner's zip); the owner's own Stage 02 run is pending.
- **Giant component**: hub control trims it by about 6 to 8 points but does not break it (transfer graph, HI-Small); about 98 percent of validation ring accounts sit inside it.
- **Communities do not recover rings** (median best-community Jaccard 0.04): they are context features; rings come from the flagged subgraph in Stage 03.
- **Window-level features**: a feature can use events later in the same window; only events after the window end are excluded.
- **Derived attributes are synthetic** and exist only for the hub-robustness ablation.
- **Placeholder FX rates**; only `amount_inr` depends on them.
- Validation baseline metrics are optimistic (threshold and early stopping use validation).
- Rows with timestamps after the stated ten days exist (up to 18 Sep).
- **Stage 03 has never run on real data.** Run time, memory and every result are unknown. The builder's checks were on synthetic data only.
- **Baselines re-implemented in Stage 03** because the Stage 01 source was not available to the builder; they are close to, not identical with, the Stage 01 baselines.
- **Rupee costs are planning assumptions**; FX rates are placeholders; at capture rate 1.0 the net-value rule may drift toward flagging everything.
- **Strict ring precision is pessimistic**: real laundering outside the 370 pattern rings counts as a false ring.
- Medium has not been run.
- Windows installs of the pinned packages are unverified. CI has not been seen running.
- check_docs only checks backticked tokens in README.md, HANDOVER.md and docs/*.md.
- **Stage 04 has not seen real Stage 03 output** (none exists yet). The exporter and API were tested on hand-made files and on the synthetic pipeline; a real run could expose size or speed problems (for example a very large number of rings).
- **Queue order uses an uncalibrated score** in an expected-value heuristic; it is not the label-based net value of Stage 03.
- **Audit log detects, not prevents, tampering**; removing the last entries is invisible without an outside copy of the head hash; one shared token and free-text analyst names mean it does not prove who acted.
- **Rate limits are per process and per client address**; behind a proxy they may be too coarse.
- **SQLite only**; Postgres and its free-tier limits are a Stage 09 task.
- Cases hold edges rebuilt from at most 500 transfers per ring.
- **Stage 05 never saw real Stage 03 output.** The metrics extractors follow the documented D9 layout, not an observed one; the demo metrics are invented in that same layout.
- **No neighbour nodes** in the case graph: the bundle holds only the ring's own accounts and edges (plan item "strongest neighbours" is open).
- **Offline mode has no analyst decisions** and no audit log.
- **cases.json is downloaded whole** in offline mode; with real data it could be large.
- The app was checked in jsdom and in one headless Chrome session on Linux; no Windows, no other browsers, no deployed host. The frontend CI workflow has not run on GitHub.
- ESLint is pinned at 9.39.5 (the version `eslint-config-next` supports); npm marks it as no longer supported upstream.
- check_docs has not been run on these docs by the builder.
- **Stage 06 has made no live model call.** Model names and free-tier limits are unverified; the verified share on real output is unknown.
- **Verified is not correct**: the verifier checks cited facts, not reasoning; the number scan only checks that a number exists somewhere in the ring's data.
- Partial edge data (truncated rings): claims are checked against the retained edges only.
- The AI layer sees transfers only; no device, IP or name data.
- **Stage 07 drift and replay have never run on real data.** Only the synthetic world and the demo bundle were used; run time, window sizes and the alert levels on the real test period are unknown. The 0.10 and 0.25 levels are a rule of thumb, not a test.
- **The drift reference is the validation split**, not the training distribution (training scores were not kept and would be in-sample).
- **Replay is retrospective**: scores use window-level features computed over the whole test window, so a live system could not have flagged rings this early. Latencies are a lower bound. Only exported rings are replayed, and latency against the truth exists only where one true ring supplies at least half of a ring's transfers.
- **The feedback rule is a heuristic and is not validated.** It is bounded (hard ceilings in code), reversible (recomputed from the audit log) and never touches stored scores, but nobody has measured whether it improves precision. The interface says so.
- **Decisions use one shared token** and free-text names; the audit log records them but does not prove who acted.
- The decision flow was tested with a mocked fetch in jsdom and against the real API through the test client; no browser session ran against a real uvicorn process in this stage.

### Stage 08

No real Elliptic run exists; dataset facts and licence are unverified; the Elliptic hub cap is untuned; no frontend page for Elliptic; ring-level metrics and rupee cost are not applicable to Elliptic; the dev-only npm advisories in the `eslint-config-next` chain remain; the evaluation-pack items from the Stage 07 handover (feedback-rule experiment, robustness tables) are still open.

### Stage 09

- No Stage 09 hosting service has been exercised; every hosting statement is from public documentation or inference. `RS_TRUSTED_PROXY_HOPS=2` is inferred.
- The committed bundle is not frozen (`evaluation_frozen: false`); the UI shows a "Numbers not frozen" banner and the smoke test warns.
- Case files in the bundle: 1 of 500 from a real model (Groq), 99 from the offline stand-in, 400 templates. Explanation quality has not been evaluated.
- Rupee amounts are artefacts of placeholder FX rates (the top ring is about 48 billion INR). Net value at loss capture 1.0 is degenerate (every strong detector earns about the same). Hub control did not improve transaction-level PR-AUC (0.6145 with, 0.6236 without). Drift: 6 of 8 test windows have too few events.
- Replay timeline: triangle labels overlap when many rings become detectable in one step (cosmetic).
- The audit log has one shared analyst token and no backup beyond the database host's own tools. The hash chain detects edits, not removal from the end.
- The Postgres store was tested on a local Postgres 16 only; per-operation connections make each request slower after idle.
- Licences: IBM data is reported as CDLA-Sharing-1.0 (owner must confirm on Kaggle; the committed bundle is derived from it); Elliptic is CC BY-NC-ND 4.0 (nothing derived from it is committed except the results table). Vercel Hobby is non-commercial use only.
- IBM citation page numbers and BibTeX are not verified.

## 11. Decision log

| Decision | Reason |
| --- | --- |
| One dataset-variant switch; per-variant processed folders | HI-Small now, Medium later without collisions |
| Candidate rings from real transfer edges; device and IP attributes only as label-blind noise | Derived attributes are synthetic |
| Every detector scored per transaction; one shared ring extractor | Like-for-like comparison |
| Cumulative past-only graph per window (train; train + val; all) | No future information beyond the window end |
| Ring recall on pattern rings only | Many laundering transactions have no pattern |
| Labels from the CSV `Is Laundering` column; patterns file gives ring structure only | The corrected download has the label; patterns cover just 3,209 of 5,177 positives. A 10-column file falls back to pattern-only labels |
| Match pattern lines to rows on all ten fields, n-th to n-th for identical rows | Rows can be identical |
| Amounts parsed with Python float on both sides | pandas' fast parser can differ in the last bit for large values |
| All ids read as text | Some ids look like numbers in scientific notation; banks have leading zeros |
| Node identity is the account string alone; banks stay attributes | The ingest report shows only 8 account strings under more than one bank |
| `amount_inr` uses amount_paid and the payment currency | Sender-side value; rates are placeholders |
| Time split by row-count quantiles (0.6 / 0.2 / 0.2), cut at a timestamp so ties never straddle | Robust to the stragglers after day 10 |
| Test rows removed before baseline features and fitting | Structural guarantee, and a test |
| Velocity features use a trailing 24-hour window | Past-only, simple, standard rule |
| XGBoost with one thread, fixed seed | Reproducible output |
| Pin only direct dependencies | Transitive packages are chosen by pip |
| Edge weight 1/log2(1+d), d the larger endpoint degree, plus a degree cap | Adaptation of the plan's attribute formula to transfer counterparties; the cap does the pruning |
| Hub cap tuned on validation: smallest cap keeping 99 percent of validation ring accounts | Uses validation labels for one parameter; never the test window |
| Community cap 200, Louvain depth 3, oversized pieces flagged | Bounded communities; the flag shows when a piece could not be split |
| igraph multilevel (Louvain) instead of networkx Louvain | networkx took over five minutes on the real component; igraph about four seconds, seeded. New pinned dependency |
| networkx not used or pinned | Stage 03 ring splitting reuses the igraph Louvain code |
| Communities are features, not ring candidates | Measured: they do not recover rings (Stage 02 negative finding) |
| Features only for accounts active in the window's own split | Small table aligned with what is scored |
| Graph features NaN for hub accounts | Not in the controlled graph; trees handle NaN |
| Reports use labels for train and validation only | The test window's labels are not read in Stage 02 |
| Stage 03 depends only on parquet contracts, not on Stage 01 code; baselines re-implemented | The incremental Stage 02 zip did not contain Stage 01 sources; one code path also makes the comparison like-for-like |
| Separate `backend/ringsentinel/evaluate/metrics.py` package from Stage 01's `backend/ringsentinel/evaluation/metrics.py` | Avoids touching Stage 01 files; the Stage 03 metrics are cross-checked against scikit-learn |
| A transfer uses graph features of its sender and receiver from its own split's window | Past-only per window; both endpoints matter for a ring |
| XGBoost trained on all positives plus 20 percent of negatives | Bounds memory; thresholds are chosen on the full validation split |
| Test split released once per detector through `SplitVault` | Structural guard for "test is scored once"; backed by a leakage test with a power check |
| Two operating points: validation-best F1 and validation-best net value | F1 is the standard comparison; net value is the plan's decision rule |
| Rings extracted from flagged transfers after scoring | Stage 02: whole-graph communities do not recover rings |
| Strict ring match (Jaccard, one-to-one, pattern rings) plus lenient ring precision | Ground truth covers pattern rings only; both views are shown |
| Cost model: ring caught on any illicit hit; legitimate account = in no illicit transfer of the split | Uses all 5,177 labels; punishes giant flagged rings |
| Rupee defaults INR 250 per review, INR 500 per wrongly included account, capture 1.0, plus a sensitivity sweep | Planning assumptions with a stated rationale in `docs/EVALUATION.md`; the sweep shows how much conclusions depend on them |
| Hub control "off" = no degree cap and all edge weights 1 | A clean switch for the detector-level ablation |
| Robustness by random transfer removal from the test-window graph | Tests decay under missing data; not an evasion tool |
| Detection latency counted in events, retrospective | Window-level features make this a lower bound; streaming is Stage 07 |
| Bundle = six canonical JSON files, hashes in `meta.json` [generated], schema-checked on write and on load | The API serves only what the exporter validated; any edit is caught at start; deterministic bytes make "the exporter output is deterministic" testable |
| No timestamps in the bundle; git commit passed in | Keeps exports byte-identical for identical inputs |
| Ring id = hash of detector name and sorted members | Stable across exports, usable as a cache key for Stage 06 case files |
| Queue ranked by `score x capture x amount - review - fp x members x (1 - score)` | An analyst has no labels; this uses only model output and the agreed rupee assumptions. Marked uncalibrated everywhere |
| At most 500 rings exported | Keeps the committed bundle small (plan section 8); the total is recorded |
| Drift, replay and AI blocks exported as explicit "not_built" placeholders | The API contract is complete now; the frontend can render empty states; nothing pretends to be real |
| Shared SQLite audit log, hash chain over canonical JSON, explicit `seq` | Standard library only; the plan asks for a hash chain; Postgres later |
| Idempotency key required on every action; decided rings closed | Retries are safe; a confirmed or dismissed decision cannot silently flip; revisiting a decision needs a deliberate design later |
| `BEGIN IMMEDIATE` plus an in-process lock around check and insert | Concurrent identical requests produce one entry |
| One shared analyst token, constant-time compare; reads open, writes and audit list gated | The plan asks for a simple analyst token; data is public demo data. Not user authentication |
| Own small rate limiter instead of a library | No new dependency; behaviour is tested with a fake clock |
| httpx2 pinned instead of httpx | Starlette's test client reports plain httpx as deprecated; httpx2 is the replacement it asks for. Used by tests only |
| Static export, client-side fetch, case id in a query string | Works with the backend asleep and on any static host; ring ids are not known at build time |
| API first, then snapshot, then demo, with the source shown in the header | Free-tier backends sleep; the analyst must never mistake a saved file for live data |
| Own SVG charts and a small d3-force layout instead of a chart or graph library | Fewer dependencies; deterministic and testable in jsdom; every chart has a table view |
| Deterministic 500-account cap by transfer volume, tie by id | Same graph on every visit; keeps the money-heavy accounts; protects the browser (risk R6) |
| Plain CSS with variables, system font stack | No font download or CSS framework; contrast checked by a test |
| Metrics extractors tolerant of layout, with explicit "not recognised" states | Stage 03 keys are unverified; never draw a wrong chart silently |
| Committed DEMO bundle with a banner on every page | The UI can be built and shown before real results exist, without passing invented numbers off as results |
| Analyst token in memory, sessionStorage only on request | A token in `localStorage` would outlive the tab; none is ever baked into the build |
| LLM gets aliases, never raw accounts; de-alias after verification | Keeps real identifiers out of third-party prompts; the verifier works on the same aliases |
| Own JSON tool-call protocol, stdlib HTTP clients | Same loop for every provider, budgets enforced in code, no new dependency |
| Template fallback is verified but not counted as LLM | The reported verified share stays honest |
| Merge accepts only the `ai` field and validates before writing | LLM output can never alter a score, rank or queue order |
| Query is a validated JSON DSL, never code or SQL | The question is untrusted text |
| jsonschema added | The plan asks for a JSON Schema for the bundle; the library is mainstream and pinned |
| Feedback shifts the threshold in log-odds by a fixed step per net dismissal, bounded, with hard ceilings in code | Transparent and testable; an env typo cannot widen the bound; reversible because it is recomputed from the audit log |
| Confirmations only cancel dismissals and never lower the threshold | Rings below the validated threshold are not in the bundle, so lowering it surfaces nothing; keeps the shift one-directional and easy to explain |
| Holds change nothing | "Not sure" is not evidence either way |
| The live queue is a read-time view; stored scores and the bundle never change | The LLM and the feedback can never alter a detector output; the evaluation stays reproducible |
| Drift reference = validation scores | Training scores were not kept and would be in-sample; documented deviation from "training distribution" |
| PSI windows are equal-width in time with exact integer edges | Float edges on nanosecond timestamps moved events across window boundaries |
| Replay is retrospective and says so | Window-level features look at the whole window; claiming live latency would overstate the system |
| Truth latency only when one true ring supplies at least half a ring's transfers | A minority share gave negative or meaningless latencies |
| `refresh` reloads the case without the spinner | A reload that unmounts the page erased the decision confirmation |
| One idempotency key per decision attempt, reused on retry | A network failure after the server answered must not record the decision twice |
| Demo drift, replay and AI blocks come from the real code on invented inputs | The interface and the demo cannot drift apart from the real documents |

### Stage 08

- Plan M8 scope chosen by the owner over the Stage 07 handover's evaluation-pack idea.
- GraphSAGE in plain PyTorch instead of PyTorch Geometric: simpler install, optional dependency.
- Razorpay webhook feed cut: needs keys and a public URL, adds attack surface, feeds no metric.
- Elliptic gets its own settings class so core `Settings` and its tests stay unchanged.
- Auth-failure lockout counts 401s only; `X-Forwarded-For` ignored by default because clients can forge it.
- pyarrow raised to 23.0.1 after pip-audit (CVE-2026-25087).

### Stage 09

- **Audit log on Postgres, not on Render's disk.** Free-tier disks are erased on restart; losing the log would silently restart the hash chain. Render's own free Postgres expires after 30 days, so Neon is used.
- **One connection per operation.** Serverless Postgres drops idle connections; a pool would hand out dead ones. The cost is a slower first request after idle.
- **Advisory lock on append.** Two API instances must not both read the same last hash and fork the chain.
- **Liveness route that never touches the database.** A health probe on a database route would keep Neon awake and burn its free compute hours.
- **Slim `requirements-api.txt`.** The API reads JSON; installing XGBoost and igraph on a 512 MB host is waste and risk. A test blocks those imports to prove they are not needed.
- **Frontend snapshots are now committed** (they were gitignored until the numbers were frozen) so the deployed site still works while the API sleeps.
- **Smoke test is standard-library only** and has an injectable `fetch`, so it can run anywhere and be tested without a network. The write check is opt-in because it adds a permanent log entry.
- **The fake provider's cached output is labelled "Offline stand-in"**, not "Written by a language model (cached)", because the earlier label was misleading in the shipped bundle.
- **README tables are generated** from the results files, so they cannot differ from what `scripts/reproduce.py` printed.
- **No freeze performed by the builder.** Freezing the evaluation is the owner's decision; the smoke test warns until it is done.


## 12. Glossary

- **Ring**: a group of accounts moving money in a coordinated way (here, one BEGIN/END block of the patterns file).
- **Pattern types**: CYCLE, GATHER-SCATTER, SCATTER-GATHER, FAN-IN, FAN-OUT, BIPARTITE, STACK, RANDOM: shapes of laundering transfers in the generator.
- **Hub**: a node connected to very many others; weak evidence, so down-weighted or dropped (degree above the hub cap).
- **IDF-style weight**: 1/log2(1+degree), applied to the larger endpoint degree of an edge.
- **Giant component**: the largest connected group of accounts; useless as a ring if it holds most accounts.
- **Community**: a group from components plus Louvain; a feature context, not a ring.
- **Window**: cumulative past-only slice of events (train; train + val; all).
- **Derived attribute**: synthetic device, IP or VPA-handle value (not real data).
- **Burstiness**: share of an account's amount moved in its busiest hour.
- **Temporal split**: train, validation and test divided by time.
- **Leakage**: test-period information influencing training or tuning.
- **PR-AUC**: here, average precision; compare with prevalence.
- **Prevalence**: share of positive rows; the PR-AUC of a random ranking.
- **Velocity**: number of transfers an account made in a trailing window.
- **Manifest**: the committed list of raw-file sizes and checksums.
- **Unringed positive**: a laundering transaction (label 1) that belongs to no pattern ring; 1,968 of 5,177 in HI-Small.
- **Variant / HI / LI**: which IBM file set is in use; higher or lower illicit ratio.
- **Net value (NV)**: rupee gain from caught rings minus review cost minus the cost of legitimate accounts inside flagged rings; the net-value threshold maximises it on validation.
- **Caught ring**: a flagged ring holding at least one flagged transfer whose label is illicit.
- **Capture rate**: share of a caught ring's illicit volume that a review could stop (1.0 by default).
- **Operating point**: a score threshold and what it yields; here F1-best or net-value-best, both chosen on validation.
- **Vault (`SplitVault`)**: the object that hides the test split from fitting and releases it once per detector.
- **Strict / lenient ring precision**: share of predicted rings matching a pattern ring (Jaccard) / containing any illicit flagged transfer.
- **Dropout (robustness)**: random removal of a share of transfers before rebuilding the graph, for testing only.
- **Snapshot bundle**: the six JSON files in `data/snapshots/` [generated] that the API and, offline, the frontend read.
- **Bundle id**: SHA-256 over the hashes of the five data files; changes when any served number changes.
- **Expected value (queue)**: the heuristic that orders the review queue; uses an uncalibrated score.
- **Audit log / hash chain**: the append-only record of analyst actions in which each entry holds the hash of the previous one.
- **Head hash**: hash of the latest audit entry; recording it elsewhere makes tail truncation detectable.
- **Idempotency key**: a client-chosen string that makes repeating the same action request safe.
- **Placeholder (bundle)**: a valid but empty document for something built in a later stage (`status: not_built`).
- **Static export**: a build that outputs plain HTML, JS and JSON files, with no server code.
- **Origin (frontend)**: which source answered a request: live API, saved snapshot, or demo bundle.
- **Demo bundle**: an invented, schema-valid bundle shipped with the frontend; marked DEMO everywhere.
- **Node cap**: the 500-account limit on the drawn case graph, chosen by transfer volume.
- **PSI**: population stability index; compares the share of scores in each reference-quantile bin between a window and the validation scores. Rule of thumb: below 0.10 stable, above 0.25 a shift (settings here, not a test).
- **Drift window**: one of the equal-width time slices of the test period that PSI is computed for.
- **Threshold offset (feedback)**: the log-odds amount the review threshold has been raised by net dismissals, between 0 and the maximum.
- **Log-odds (logit)**: ln(p / (1 - p)); the scale on which the feedback shift is added.
- **Adjusted score / adjusted expected value**: the score and queue value after the offset; computed on read, never stored.
- **Live rank**: position in the feedback-adjusted queue; only open rings above the shifted threshold with a positive value have one.
- **Replay**: stepping through the test period to see when each flagged ring became detectable; retrospective.
- **Assembly time / detection latency**: time from a ring's first transfer to the moment its flagged transfers touch the minimum ring size / time from the true ring's first transfer to that moment.
- **Replayed response**: the server's answer to a repeated request with the same idempotency key; `replayed: true`, nothing new recorded.

- **Elliptic**: public Bitcoin transaction graph (Weber et al. 2019) with licit/illicit labels; second dataset in Stage 08.
- **Time step**: Elliptic's two-week bucket (49 of them); used for the temporal split.
- **GraphSAGE**: neural network that averages neighbour features; optional detector.
- **authfail bucket**: per-client count of failed token checks.

### Stage 09

- **Liveness route**: GET /api/v1/live; answers without touching the database or the bundle.
- **Smoke test**: `scripts/smoke_deployed.py`, a read-mostly check of a deployed API and site.
- **Offline stand-in**: the "fake" LLM provider, a fixed routine used for tests and offline runs; its output is labelled as such.
- **Freeze**: marking the bundle `evaluation_frozen: true` with `--frozen`; a promise not to change numbers without rerunning everything.
- **Advisory lock**: a Postgres lock held for one transaction, used so two API instances cannot both extend the hash chain from the same last entry.

## 13. How to regenerate every artifact

Windows cmd, repo root, venv active:

```
pip install -r requirements.txt
python scripts\inspect_schema.py --trans data\raw\HI-Small_Trans.csv --patterns data\raw\HI-Small_Patterns.txt
python scripts\run_stage01.py
python scripts\run_stage02.py
python scripts\ablation_giant_component.py
python scripts\run_stage03.py
python scripts\reproduce.py
python scripts\export_snapshots.py
python scripts\run_stage06.py --provider fake
python scripts\make_demo_bundle.py
python scripts\sync_frontend_snapshots.py
python scripts\run_api.py
pytest
ruff check .
python scripts\check_docs.py
```

Individual steps: `python scripts\run_stage01.py --step ingest --force` (and `split`, `baselines`); `python scripts\run_stage02.py --step noise|tune|features|ablation --window train|val|test`. Stage 03: `python scripts\run_stage03.py --step detect|evaluate|ablate|robustness`, or `python scripts\reproduce.py` for everything plus `docs/EVALUATION_RESULTS.md` [generated] (`--evaluate-only` reuses the scores). Stage 06: `python scripts\run_stage06.py --provider fake|groq|gemini [--limit N|--all] [--refresh] [--no-apply]` writes `ai_cases.json` [generated] and `ai_report.json` [generated] and merges into the bundle; `python scripts\ai_query.py "question"`. Cached model replies live in `data/processed/<variant>/ai_cache/` [generated]; deleting it forces fresh calls. Stage 05 (from `frontend`): `npm ci`, `npm run dev`, `npm run check`, `npm run build`; from the repo root `python scripts\make_demo_bundle.py [--check]` rebuilds the demo bundle and `python scripts\sync_frontend_snapshots.py [--src DIR]` copies the real bundle into the frontend. Stage 04 and 07: `python scripts\export_snapshots.py [--git-commit SHA] [--frozen] [--max-rings N] [--no-edges] [--no-monitor] [--out DIR]` writes `data/snapshots/` [generated]; `python scripts\run_api.py [--port 8000]` serves it (set `RS_ANALYST_TOKEN` first for actions). The audit database is created on first start and is not regenerated: deleting it deletes the log.

Stage 08 (after placing the Elliptic CSVs in `data\raw\elliptic`):

```
python scripts\run_stage08.py verify --write-manifest
python scripts\run_stage08.py run
python scripts\run_stage08.py table
python scripts\secrets_scan.py
```

Stage 09 (Windows cmd, repo root):

```
pip install -r requirements.txt
python scripts\export_snapshots.py --frozen --git-commit <short sha>
python scripts\sync_frontend_snapshots.py
python scripts\sync_readme_results.py
python scripts\smoke_deployed.py --api https://<api> --web https://<site> --expect-postgres --expect-docs-off --wait 120
set RS_TEST_POSTGRES_URL=postgresql://USER:PASSWORD@localhost:5432/ringsentinel_test
pytest
```

Hosting steps are in `docs/DEPLOYMENT.md`; the three diagrams are regenerated from `docs/DIAGRAM_SPECS.md`.
