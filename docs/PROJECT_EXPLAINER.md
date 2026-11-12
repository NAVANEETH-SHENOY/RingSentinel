# RingSentinel: zero-context project explainer

Written for a reader (human or LLM) who has only the project zip. Current milestone: **Stage 01 (data, temporal split, baselines) built; waiting for the owner to run it on the real data; tag v0.2.0 not yet applied**. Anything that does not exist yet is marked [planned]. If this file and the code disagree, the code wins; run `python scripts/check_docs.py` to catch stale paths.

## 1. Plain-language summary

RingSentinel is a tool for fraud analysts. Money moves between accounts. Sometimes groups of accounts work together to move illicit money, which is hard to see one transaction at a time. RingSentinel will link accounts through the transfers between them, find groups that behave like a coordinated ring, rank the groups by how worthwhile they are to review, and explain each one. A human analyst then confirms, dismisses or holds each case; the tool never blocks anything itself. It is judged on honest measurement: how many real rings it finds, how many false alarms it raises, and what those false alarms cost in rupees.

It is built for the Razorpay AI Buildathon, Track 02 (AI Risk Manager), as a solo project, and it is defense-only. It uses a public synthetic dataset (IBM anti-money-laundering transactions), not real customer data.

So far the project can load and clean that dataset, label the known laundering rings, split the data by time, and score two simple baseline detectors. The graph-based detector, the explanations, the analyst interface and the deployment do not exist yet.

## 2. Technical summary

- Stack: Python 3.10+ (owner uses 3.13), pandas, numpy, pyarrow, scikit-learn, XGBoost, pydantic, pytest, ruff, all pinned in `requirements.txt`. Later: networkx, FastAPI, Next.js, SQLite or Postgres [planned].
- Architecture: a deterministic offline pipeline (ingest, temporal split, graph, features, detectors, ring extraction, evaluation) exports static JSON snapshots; a thin API and a UI sit on top [planned]. See `docs/ARCHITECTURE.md`.
- Implemented now: (D1) checksum manifest; (D2) chunked CSV reader to a typed event table, pattern parser, label attachment, INR amount, validation; (D4) time-based split with ring assignment; two baselines (velocity rule; tabular XGBoost) scored on the validation split; shared metrics.
- Core logic still to come [planned]: transfer graph with hub control (weight 1/log2(1+degree), degree cap), candidate rings (components plus Louvain), community features, graph-feature XGBoost, ring-level Jaccard match, net-value cost model, LLM investigator with a verifier, hash-chained audit log, drift (PSI).
- One setting, `RS_DATASET_VARIANT`, selects HI-Small (default), LI-Small, HI-Medium or LI-Medium; all paths derive from it.

## 3. Current state

| Item | State |
| --- | --- |
| Milestone | M0 done and confirmed on the owner's Windows machine. M1 / Stage 01 built; owner has not yet run the real-data pipeline |
| Works (tested on synthetic data and, on the owner's machine, the real HI-Small files) | Header check, manifest, patterns parser, ingestor, label attachment, split, velocity rule, tabular XGBoost, metrics, runner |
| Verified on the real files | Only the schema inspection (owner's report). The ingestor, split and baselines have not been run on the real 5-million-row file |
| Does not exist yet | Graph, features, graph detector, Isolation Forest, ring evaluation, cost model, AI layer, API, UI, drift, replay, deployment |
| Headline numbers | None yet. The only metrics code path produces validation-split baselines; no test-split result exists |

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
| `backend/ringsentinel/ingest/diagnose.py` | Read-only matching diagnostic: `diagnose_matching()`, `format_diagnosis()`, `diagnose_legs()`, `format_legs()`, `diagnose_account_columns()`, `format_account_columns()` | `scripts/diagnose_matching.py` | `read_transactions()` output, `parse_patterns()` output |
| `scripts/diagnose_matching.py` | Prints and saves which field disagrees between patterns file and CSV | owner | `backend/ringsentinel/ingest/diagnose.py` |
| `scripts/run_stage01.py` | Command line for Stage 01 | owner | `backend/ringsentinel/stage01.py` |
| `scripts/inspect_schema.py` | Prints real columns and layout of the raw files (standard library only) | owner | none |
| `scripts/check_docs.py` | Fails if docs name a missing path or function | CLI, CI, tests | filesystem |
| `backend/tests/conftest.py` | Builds a synthetic dataset in the real layout | all data tests | none |
| `backend/tests/test_*.py` | See section 8 | pytest | the code under test |
| `frontend/package.json` | Frontend shell, no dependencies yet | npm | none |
| `docs/*.md` | Architecture, data facts, per-stage notes, this file | Humans | none |

Planned (created in the stage named): `backend/ringsentinel/graph/` [planned, Stage 02], `backend/app/` [planned, Stage 04], `backend/ringsentinel/ai/` [planned, Stage 06], `docs/EVALUATION.md` [planned, Stage 03], `docs/DIAGRAM_SPECS.md` [planned, Stage 09], `scripts/reproduce.py` [planned, Stage 03].

## 5. Runtime flows

Stage 01 pipeline (`python scripts/run_stage01.py`, `main()` in `scripts/run_stage01.py`):
1. `run_verify()` compares `data/raw` files with `data/raw/MANIFEST.json` using `verify_files()`.
2. `run_ingest()` calls `normalize()`: `read_transactions()` reads the CSV in chunks (all columns as text, ids kept as strings, sender and receiver sides share category sets, sorted by time) then `add_amount_inr()`; `parse_patterns()` reads the patterns file; `attach_labels()` matches pattern lines to rows and sets `is_illicit`, `ring_id`, `ring_type`; the label rate and unmatched share are checked; `validate_events()` runs; `build_rings_truth()` summarizes rings; files are written to `data/processed/hi_small/` [generated].
3. `run_split()` calls `build_split()`: cut times from row-count quantiles, `check_no_overlap()`, ring assignment by earliest event; writes the split table and metadata.
4. `run_baselines()` calls `prepare_baseline_frames()`, which returns only train and validation rows. It scores the velocity rule (`velocity_scores()`, threshold from validation), trains XGBoost on train with early stopping on validation (`train_xgb()`), evaluates both with `evaluate_scores()`, and writes `baseline_metrics.json` [generated].

Loading configuration: `get_settings()` reads `.env` then environment variables; blank values count as unset; unsupported variants raise a validation error.

Checking the docs: `main()` in `scripts/check_docs.py` calls `find_problems()`, which uses `extract_tokens()` and `check_token()`.

Inspecting raw files: `main()` in `scripts/inspect_schema.py` calls `inspect_csv()` and `inspect_patterns()`.

The graph pipeline, serving a request, analyst actions and case generation are [planned].

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

D3 and D5 to D13 are [planned]; schemas will be written here as each stage creates them.

## 7. Configuration

| Variable | Default | If wrong |
| --- | --- | --- |
| `RS_DATASET_VARIANT` | HI-Small | Unsupported value raises a validation error; file names are derived from it, so missing files are reported by the verify step |
| `RS_DATA_DIR` | `<repo>/data` | Pipeline reads and writes in the wrong place |
| `RS_SEED` | 42 | Non-integer raises ValueError; changes seeded results |
| `RS_TRAIN_FRAC`, `RS_VAL_FRAC` | 0.6, 0.2 | Must be in (0,1) and sum below 1, else a validation error |

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

Order to rule out causes: environment (venv active, installs done), working directory, config values, input files (verify step), then code. Logs: pytest output, console output of `scripts/run_stage01.py`, and the ingest report.

## 10. Known issues and limits

- **Labels versus rings**: labels come from the CSV `Is Laundering` column (5,177 positives); only 3,209 are in a pattern ring (see `docs/DATA.md`).
- **Positive rate drifts upward** across the time split (0.075, 0.107, 0.177 percent for train, val, test).
- **Real-data status**: the owner ran the pipeline on the real corrected files; the builder's environment cannot reach Kaggle, so any rerun there needs the files attached.
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
| Candidate rings from real transfer edges; device and IP attributes only as label-blind noise [planned, Stage 02] | Derived attributes are synthetic |
| Every detector scored per transaction; one shared ring extractor [planned, Stage 03] | Like-for-like comparison |
| Cumulative past-only graph per window [planned, Stage 02] | No future information |
| Ring recall on pattern rings only | Many laundering transactions have no pattern |
| Labels from the CSV `Is Laundering` column; patterns file gives ring structure only | The corrected download has the label; patterns cover just 3,209 of 5,177 positives. A 10-column file falls back to pattern-only labels |
| Match pattern lines to rows on all ten fields, n-th to n-th for identical rows | Rows can be identical |
| Amounts parsed with Python float on both sides | pandas' fast parser can differ in the last bit for large values |
| All ids read as text | Some ids look like numbers in scientific notation; banks have leading zeros |
| Node identity for the graph will be the account string, banks as attributes [planned, Stage 02]; revisit if the ingest report shows many accounts under several banks | One sample row showed the same account string at two banks |
| `amount_inr` uses amount_paid and the payment currency | Sender-side value; rates are placeholders |
| Time split by row-count quantiles (0.6 / 0.2 / 0.2), cut at a timestamp so ties never straddle | Robust to the stragglers after day 10 |
| Test rows removed before baseline features and fitting | Structural guarantee, and a test |
| Velocity features use a trailing 24-hour window | Past-only, simple, standard rule |
| XGBoost with one thread, fixed seed | Reproducible output |
| Pin only direct dependencies | Transitive packages are chosen by pip |

## 12. Glossary

- **Ring**: a group of accounts moving money in a coordinated way (here, one BEGIN/END block of the patterns file).
- **Pattern types**: CYCLE, GATHER-SCATTER, SCATTER-GATHER, FAN-IN, FAN-OUT, BIPARTITE, STACK, RANDOM: shapes of laundering transfers in the generator.
- **Hub**: a node connected to very many others; weak evidence, so down-weighted or dropped [planned].
- **IDF-style weight**: 1/log2(1+degree) [planned].
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
pytest
ruff check .
python scripts\check_docs.py
```

Individual steps: `python scripts\run_stage01.py --step ingest --force` (and `split`, `baselines`). Graph, evaluation and snapshot artifacts: [planned] (`scripts/reproduce.py` [planned] from Stage 03).
