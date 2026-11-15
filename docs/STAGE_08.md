# Stage 08: second dataset (Elliptic), optional GraphSAGE, hardening (M8)

Tag: v0.9.0 (after the owner runs the tests and, ideally, the real Elliptic run). Branch: `stage-08-elliptic-hardening`.

Built on the owner's merged Stage 07 repository (main at 17e3ce9, including the owner's Groq provider changes). Nothing under `backend/ringsentinel/ai/` and no frontend file was touched.

## What was built

| Item | Where |
| --- | --- |
| Elliptic file layout and checks (expected columns marked VERIFY) | `backend/ringsentinel/elliptic/schema.py`, `backend/ringsentinel/elliptic/load.py` |
| Elliptic settings (own file, so the core `Settings` and its tests are unchanged) | `backend/ringsentinel/elliptic/settings.py` |
| Time-step split (shared `check_no_overlap`) | `backend/ringsentinel/elliptic/split.py` |
| Hub-controlled graph features from the Stage 02 builder | `backend/ringsentinel/elliptic/graph.py` |
| Detectors, protocol, per-step drift, results tables | `backend/ringsentinel/elliptic/pipeline.py` |
| Optional GraphSAGE (plain PyTorch) | `backend/ringsentinel/elliptic/gnn.py`, `requirements-gnn.txt` |
| Synthetic Elliptic-format files for tests and dry runs | `backend/ringsentinel/elliptic/synthetic.py` |
| Command line: verify, run, table, demo | `scripts/run_stage08.py` |
| API hardening | `backend/app/main.py`, `backend/app/config.py`, `backend/app/ratelimit.py` |
| Secrets review tool | `scripts/secrets_scan.py` |
| Dependency and secrets audit in CI | `.github/workflows/audit.yml` |

## Decisions and deviations from the plan (flagged, not silent)

1. **Scope.** The Stage 07 handover described Stage 08 as the evaluation pack (ablation and robustness tables, a validation experiment for the feedback rule, `scripts/reproduce.py` for drift and replay). The plan's M8 is the second dataset plus hardening. The owner chose the plan's M8, so the evaluation-pack items move to Stage 09 or later and are still open.
2. **"Same harness" means the same protocol and shared code, not the same columns.** Elliptic nodes are Bitcoin transactions with anonymised features. There are no accounts, no amounts, no ring labels and no clock times inside a time step. So ring-level precision and recall, the rupee cost model and the velocity rule cannot be computed and are reported as not applicable (`meta.not_applicable` in `metrics.json` [generated]). Everything that can be shared is shared: `build_window_features()` (graph, hub control, IDF weights, communities, PageRank), `fit_xgb()`, `ImputedIsolationForest`, `SplitVault`, `average_precision()`, `best_f1_threshold()`, `precision_recall_f1()`, `psi()` and `classify()`.
3. **GraphSAGE uses plain PyTorch, not PyTorch Geometric.** The plan says "if PyTorch Geometric installs cleanly". A two-layer mean-aggregator GraphSAGE needs only a sparse matrix product, so `backend/ringsentinel/elliptic/gnn.py` avoids the harder install. PyTorch itself is optional (`requirements-gnn.txt`), is not in `requirements.txt`, and its tests skip when it is absent.
4. **Razorpay test-mode webhook feed is cut.** It needs the owner's keys and a public URL, adds attack surface, and cannot feed any metric. The Stage 09 demo already runs from snapshots. Documented as cut, as the plan allows.
5. **Split by time step.** Train steps 1 to 29, validation 30 to 34, test 35 to 49 (`RS_ELLIPTIC_TRAIN_LAST_STEP`, `RS_ELLIPTIC_VAL_LAST_STEP`). The test period matches the one most papers use. The 29/34 cut is this project's own choice, so numbers are not directly comparable with papers that train on steps 1 to 34. Only the order of steps is real; `backend/ringsentinel/elliptic/split.py` maps a step to a pseudo date so the shared overlap check can run.

## Elliptic protocol

Dataset facts below come from the paper and public descriptions, **not from the real files** (the build environment cannot download them). `python scripts\run_stage08.py verify` prints the real header, widths and counts; compare them with this list before trusting a run.

- Three files: elliptic_txs_features.csv (no header; txId, time step, then 165 features: 93 local and 72 one-hop aggregates, 167 columns in all), elliptic_txs_classes.csv (`txId,class`; 1 illicit, 2 licit, unknown), elliptic_txs_edgelist.csv (`txId1,txId2`, a payment flow). About 203,769 transactions, 234,355 edges, 49 time steps. All of this is VERIFY.
- Only labelled transactions are fitted and judged. Unlabelled ones stay in the graph and are scored (labels are not needed to score), which feeds the label-free drift monitor.
- Thresholds: the F1 threshold is chosen on validation only. The test steps are scored once per detector through `SplitVault.release_test()`.
- Graph features are built per window exactly as for IBM. An edge belongs to the later of its two time steps. The train window therefore sees train edges only, validation sees train plus validation, test sees everything. Columns derived from the dummy amount or the pseudo clock are excluded by an allow-list (`GRAPH_COLUMNS`, with the reason in `EXCLUDED_COLUMNS`).
- Hub cap: `RS_ELLIPTIC_HUB_CAP` (default `RS_HUB_CAP` if set, else 50). It is **not tuned**, because tuning needs ring labels. The `graph_xgb_nohub` ablation shows what the cap does.

| Detector | What it is | Uses graph |
| --- | --- | --- |
| `degree_rule` | score = number of distinct neighbours (sanity floor, not a velocity rule) | yes |
| `local_iforest` | Isolation Forest on the 93 local features (unsupervised) | no |
| `local_xgb` | XGBoost on the 93 local features (the tabular baseline) | no |
| `all_xgb` | XGBoost on local plus the 72 aggregates Elliptic supplies | provider's, not ours |
| `graph_xgb` | XGBoost on local plus RingSentinel's graph features (the contribution) | yes |
| `graph_xgb_nohub` | the same with no hub cap (ablation) | yes |
| `graphsage` | optional GraphSAGE on the local features with message passing | yes |

Per test time step the report gives precision, recall, F1, PR-AUC and the PSI of that step's scores against the validation scores, so a late shift (the literature reports that models degrade sharply after about step 43; **verify** in the paper) can be seen as a PSI alert. Whether it appears in the real data is unknown until the real run.

## How to run (Windows cmd, repo root)

```
python scripts\run_stage08.py demo
python scripts\run_stage08.py verify
python scripts\run_stage08.py verify --write-manifest
python scripts\run_stage08.py run
python scripts\run_stage08.py table
```

`demo` runs everything on **synthetic** files in a temporary folder; its numbers mean nothing. For the real run, unzip the three Kaggle CSV files into `data\raw\elliptic` first. `--write-manifest` records sizes and SHA-256 in the shared `data/raw/MANIFEST.json` (commit it; the raw files stay ignored). Optional GraphSAGE: `pip install -r requirements-gnn.txt`, then `python scripts\run_stage08.py run --gnn`. `table` writes `docs/RESULTS_TABLE.md` [generated], the two-dataset table (IBM rows say "not run" until Stage 03 has produced `metrics.json` [generated]).

## Hardening

| Change | Detail |
| --- | --- |
| Failed-login lockout | 401 responses fill a per-client `authfail` bucket (`RS_RATE_LIMIT_AUTHFAIL_PER_MIN`, default 10). A full bucket answers 429 with `Retry-After` for the rest of the minute, even for the right token. Behind a shared address this can lock out a real analyst for a minute; that is the price of the protection. |
| Real client address | `RS_TRUSTED_PROXY_HOPS` (default 0 = ignore `X-Forwarded-For`, which a client can forge). With N trusted proxies the Nth entry from the right is used; invalid entries fall back to the socket peer. Needed in Stage 09: behind a host proxy every request otherwise shares one address. Check the host's documentation for the hop count before setting it. |
| Request size | `RS_MAX_BODY_BYTES` (default 16384). Larger bodies get 413; chunked bodies get 411; a bad `Content-Length` gets 400. Checked before any route reads the body. |
| Response headers | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` on every response, including 429 and 413. `Cache-Control: no-store` on writes and the audit list. No Content-Security-Policy is set: the API only returns JSON, and the interactive docs page loads assets that a strict policy would break. |
| API docs switch | `RS_API_DOCS=0` removes the interactive docs and the OpenAPI file (recommended for the public deployment). |
| Limiter memory | The in-process limiter sweeps expired keys once a minute and drops the stalest keys above 10,000, so a flood of fresh addresses cannot grow it without bound. |

### Secrets review

- `python scripts\secrets_scan.py` (tracked and not-ignored files, plus every commit) found **no key-shaped string** in the working tree or in the 39 commits of the owner's repository at the time of the build. It prints only file, line, rule and four characters, never the value.
- One real gap fixed: kaggle.json was not in `.gitignore` (now kaggle.json and .kaggle/ are).
- The Groq provider (`backend/ringsentinel/ai/provider.py`) sends keys in headers only and redacts them from error text. Reviewed, not changed.
- **Action for the owner:** the repository zip uploaded for this stage contained a local `.env` with a real-looking Groq key. It is ignored by git, but it was shared outside your machine. Revoke it in the Groq console and create a new one.

### Dependency audit

- Python (`pip-audit` on the installed environment, transitive packages included): one finding, `pyarrow 22.0.0`, CVE-2026-25087 (use after free when reading an Arrow IPC file with pre-buffering on). This project only reads its own Parquet files, so it was not exploitable; `requirements.txt` now pins `pyarrow==23.0.1`, the first fixed version, and the full backend suite passes with it. After the change `pip-audit` reports no known vulnerabilities.
- Frontend production dependencies: `npm audit --omit=dev` reports 0. All dependencies: 8 moderate advisories, all in the `eslint-config-next` chain (a `minimatch` denial-of-service in lint tooling). They are dev-only and not shipped in the static export. The suggested fix is a **downgrade** of `eslint-config-next` to 15.x, which was not applied. Revisit when a 16.x release updates the chain.
- `.github/workflows/audit.yml` repeats these checks weekly and on pull requests. It has never run on GitHub.

## Tests

New files: `backend/tests/test_stage08_load.py`, `backend/tests/test_stage08_graph.py`, `backend/tests/test_stage08_pipeline.py`, `backend/tests/test_stage08_gnn.py`, `backend/tests/test_stage08_hardening.py`, `backend/tests/test_stage08_secrets_scan.py`, with `backend/tests/s08_world.py`. They guard: loader and schema errors, step-based split without overlap, windows that never see future edges, hub cap behaviour, test period destroyed without changing anything fitted, the vault releasing the test split once, thresholds chosen on validation, PR-AUC equal to scikit-learn's, determinism, PSI alerting on a shifted period and staying quiet without one, GraphSAGE determinism and no label access, lockout, proxy address, body limits, headers, and the scanner's rules, including a key that exists only in history.

Test status with real counts: see `HANDOVER.md`.

## Known limits

- **No real Elliptic number exists yet.** Every result so far is from synthetic files. Column counts, class codes, the number of time steps and the licence are unverified until `verify` is run on the real download.
- The two-dataset table compares roles, not difficulty: prevalence, features and what "positive" means differ between the datasets.
- The Elliptic hub cap is untuned. The synthetic world has a hub of degree 45, so its `graph_xgb_nohub` ablation equals `graph_xgb` at the default cap of 50. The real data may differ.
- The aggregate features in `all_xgb` were computed by Elliptic from neighbours, possibly using information from neighbouring time steps; they are included because the literature uses them, and kept separate from our own graph features for that reason.
- `local_*` and `graph_*` rows can look strong because the dataset's local features are strong; judge the graph contribution by the gap between `local_xgb` and `graph_xgb`, not by the absolute level.
- No frontend page shows Elliptic. The results are in `docs/RESULTS_TABLE.md` [generated] and the printed tables; surfacing them in the dashboard is a Stage 09 option.
- GraphSAGE and `requirements-gnn.txt`: `torch==2.15.0` was tested on Linux with Python 3.13 (CPU). The Windows wheel for your Python was not tested.
