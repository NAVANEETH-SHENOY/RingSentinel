# RingSentinel: zero-context project explainer

Written for a reader (human or LLM) who has only the project zip. Current milestone: **Stage 02 (noise layer, transfer graph with hub control, features) built and run by the builder on the real data; the owner's run and tag v0.3.0 are pending. Stage 01 is confirmed and tagged v0.2.0**. Anything that does not exist yet is marked [planned]. If this file and the code disagree, the code wins; run `python scripts/check_docs.py` to catch stale paths.

## 1. Plain-language summary

RingSentinel is a tool for fraud analysts. Money moves between accounts. Sometimes groups of accounts work together to move illicit money, which is hard to see one transaction at a time. RingSentinel will link accounts through the transfers between them, find groups that behave like a coordinated ring, rank the groups by how worthwhile they are to review, and explain each one. A human analyst then confirms, dismisses or holds each case; the tool never blocks anything itself. It is judged on honest measurement: how many real rings it finds, how many false alarms it raises, and what those false alarms cost in rupees.

It is built for the Razorpay AI Buildathon, Track 02 (AI Risk Manager), as a solo project, and it is defense-only. It uses a public synthetic dataset (IBM anti-money-laundering transactions), not real customer data.

So far the project can load and clean that dataset, label the known laundering rings, split the data by time, score two simple baseline detectors, and turn the transfers into an account graph with hub control and a table of per-account and per-community features. The graph-based detector, ring extraction, the explanations, the analyst interface and the deployment do not exist yet.

## 2. Technical summary

- Stack: Python 3.10+ (owner uses 3.13), pandas, numpy, pyarrow, scikit-learn, XGBoost, pydantic, pytest, ruff, scipy, python-igraph, all pinned in `requirements.txt`. Later: FastAPI, Next.js, SQLite or Postgres, possibly networkx for ring extraction [planned].
- Architecture: a deterministic offline pipeline (ingest, temporal split, graph, features, detectors, ring extraction, evaluation) exports static JSON snapshots; a thin API and a UI sit on top [planned]. See `docs/ARCHITECTURE.md`.
- Implemented now: (D1) checksum manifest; (D2) chunked CSV reader to a typed event table, pattern parser, label attachment, INR amount, validation; (D4) time-based split with ring assignment; two baselines (velocity rule; tabular XGBoost) scored on the validation split; shared metrics; (D3) label-blind synthetic noise layer; (D5) cumulative past-only transfer graph per window with IDF edge weights, a degree cap tuned on validation, a pruning report and Louvain-split communities; (D6) node and community features.
- Core logic still to come [planned]: graph-feature XGBoost, ring extraction from the scored subgraph, ring-level Jaccard match, net-value cost model, LLM investigator with a verifier, hash-chained audit log, drift (PSI).
- One setting, `RS_DATASET_VARIANT`, selects HI-Small (default), LI-Small, HI-Medium or LI-Medium; all paths derive from it.

## 3. Current state

| Item | State |
| --- | --- |
| Milestone | M0 and M1 (Stage 01) done and confirmed on the owner's Windows machine, pushed. M2 / Stage 02 built; builder ran it on the real data; owner's run pending |
| Works (tested on synthetic data and on the real HI-Small files) | Header check, manifest, patterns parser, ingestor, label attachment, split, velocity rule, tabular XGBoost, metrics, Stage 01 runner, noise layer, graph builder, hub control, communities, node and community features, giant-component ablation, Stage 02 runner |
| Verified on the real files | Stage 01 (owner: 85 tests passed, pipeline run) and Stage 02 (builder's run of every step; the owner's run is pending) |
| Does not exist yet | Graph detector, Isolation Forest, ring extraction and evaluation, cost model, AI layer, API, UI, drift, replay, deployment |
| Headline numbers | None yet. Validation-split baselines exist (Stage 01); Stage 02 reports graph diagnostics only; no test-split result exists |

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
| `frontend/package.json` | Frontend shell, no dependencies yet | npm | none |
| `docs/*.md` | Architecture, data facts, per-stage notes, this file | Humans | none |

Planned (created in the stage named): `backend/app/` [planned, Stage 04], `backend/ringsentinel/ai/` [planned, Stage 06], `docs/EVALUATION.md` [planned, Stage 03], `docs/DIAGRAM_SPECS.md` [planned, Stage 09], `scripts/reproduce.py` [planned, Stage 03].

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

Serving a request, analyst actions and case generation are [planned].

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

D7 to D13 are [planned]; schemas will be written here as each stage creates them.

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

Reserved for later stages and listed in `.env.example`: Kaggle credentials, analyst token, audit database URL, LLM provider and keys. `config/fx_rates_inr.json` holds the placeholder currency rates; a currency missing from it stops ingest.

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

Run: `pytest` from the repo root.

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
| Feature values change after a rerun | Hub cap or community settings changed, or a different platform | `effective_hub_cap()`, `Settings` | Compare `hub_cap` in `pruning_report.json` [generated] | Fix the settings; features are deterministic for fixed settings |

Order to rule out causes: environment (venv active, installs done), working directory, config values, input files (verify step), then code. Logs: pytest output, console output of `scripts/run_stage01.py`, and the ingest report.

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
- Medium has not been run.
- Windows installs of the pinned packages are unverified. CI has not been seen running.
- check_docs only checks backticked tokens in README.md, HANDOVER.md and docs/*.md.

## 11. Decision log

| Decision | Reason |
| --- | --- |
| One dataset-variant switch; per-variant processed folders | HI-Small now, Medium later without collisions |
| Candidate rings from real transfer edges; device and IP attributes only as label-blind noise | Derived attributes are synthetic |
| Every detector scored per transaction; one shared ring extractor [planned, Stage 03] | Like-for-like comparison |
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
| networkx not pinned yet | Nothing uses it; pin when Stage 03 needs it |
| Communities are features, not ring candidates | Measured: they do not recover rings (Stage 02 negative finding) |
| Features only for accounts active in the window's own split | Small table aligned with what is scored |
| Graph features NaN for hub accounts | Not in the controlled graph; trees handle NaN |
| Reports use labels for train and validation only | The test window's labels are not read in Stage 02 |

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
- **Net value, PSI, snapshot**: see `docs/ARCHITECTURE.md` and later stages.

## 13. How to regenerate every artifact

Windows cmd, repo root, venv active:

```
pip install -r requirements.txt
python scripts\inspect_schema.py --trans data\raw\HI-Small_Trans.csv --patterns data\raw\HI-Small_Patterns.txt
python scripts\run_stage01.py
python scripts\run_stage02.py
python scripts\ablation_giant_component.py
pytest
ruff check .
python scripts\check_docs.py
```

Individual steps: `python scripts\run_stage01.py --step ingest --force` (and `split`, `baselines`); `python scripts\run_stage02.py --step noise|tune|features|ablation --window train|val|test`. Evaluation and snapshot artifacts: [planned] (`scripts/reproduce.py` [planned] from Stage 03).
