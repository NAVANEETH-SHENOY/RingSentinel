# RingSentinel: zero-context project explainer

Written for a reader (human or LLM) who has only the project zip. Current milestone: **Stage 00 (scaffold), tag v0.1.0; Stage 01 part 1 (schema inspector) delivered, ingestor not yet written**. Anything that does not exist yet is marked [planned]. If this file and the code disagree, the code wins; run `python scripts/check_docs.py` to catch stale paths.

## 1. Plain-language summary

RingSentinel is a tool for fraud analysts. Money moves between accounts. Sometimes groups of accounts work together to hide or move illicit money, which makes them hard to spot one transaction at a time. RingSentinel will link accounts through the transfers between them, find groups that behave like a coordinated ring, rank the groups by how worthwhile they are to review, and explain each one in plain language. A human analyst then confirms, dismisses or holds each case; the tool never blocks anything itself. It is judged on honest measurement: how many real rings it finds, how many false alarms it raises, and what those false alarms cost in rupees.

It is built for the Razorpay AI Buildathon, Track 02 (AI Risk Manager), as a solo project, and it is defense-only. It uses a public synthetic dataset, not real customer data.

At Stage 00 none of that detection exists yet. What exists is the empty, tested skeleton the rest will be built on.

## 2. Technical summary

- Stack: Python 3.10+ backend (pydantic, python-dotenv, pytest, ruff pinned now; pandas, pyarrow, networkx, scikit-learn, XGBoost, FastAPI added in later stages [planned]), Next.js frontend [planned, Stage 05], SQLite locally and free Postgres when deployed for the audit log [planned].
- Architecture: a deterministic offline pipeline (ingest, temporal split, graph, features, detectors, ring extraction, evaluation) exports static JSON snapshots. A thin FastAPI layer serves them and appends analyst actions to a hash-chained audit log. A Next.js UI reads the API, or the snapshots directly when the API is asleep. See `docs/ARCHITECTURE.md`.
- Core logic [planned]: entity graph from real account-to-account transfers; hub control with weight 1/log2(1+degree) and a degree cap; candidate rings from thresholded edge strength, connected components and Louvain splits; community features; XGBoost scoring chosen on validation only; ring match by Jaccard at least 0.5; net-value cost model in rupees; an LLM investigator whose every cited fact is verified against the graph; population stability index for drift.
- Dataset variant switch: one setting, `RS_DATASET_VARIANT`, selects HI-Small (default), LI-Small, HI-Medium or LI-Medium. All paths derive from it.

## 3. Current state

| Item | State |
| --- | --- |
| Milestone reached | M0 / Stage 00 done. M1 / Stage 01 in progress: part 1 (schema inspector) delivered; the ingestor, splitter and baselines wait for the real schema |
| Works | Settings and variant switch (`backend/ringsentinel/config.py`), docs consistency checker (`scripts/check_docs.py`), assumption-free schema inspector (`scripts/inspect_schema.py`), tests, lint, CI workflow file |
| Does not exist yet | Everything in data, graph, models, evaluation, AI layer, API, frontend, drift, replay, deployment |
| Verified by execution | Tests, ruff and check_docs were run in the build environment (Linux, Python 3.13). They have not yet been run on the owner's Windows machine or on GitHub Actions |

## 4. Repo map

| Path | What it does | Called by | Calls |
| --- | --- | --- | --- |
| `README.md` | Public overview, filled in progressively | Humans; `scripts/check_docs.py` reads it | none |
| `HANDOVER.md` | Where to continue plus a paste-ready prompt | Next chat session | none |
| `CHANGELOG.md` | One entry per tag | Humans | none |
| `requirements.txt` | Pinned Python dependencies | `pip install -r`; CI | none |
| `pyproject.toml` | pytest settings (paths) and ruff settings | pytest, ruff | none |
| `.env.example` | Env var names only; copy to `.env` | Humans; `backend/ringsentinel/config.py` reads `.env` via python-dotenv | none |
| `.gitignore`, `.gitattributes` | Keep data and secrets out of git; force LF line endings | git | none |
| `.github/workflows/ci.yml` | CI: ruff, check_docs, pytest on Ubuntu and Windows | GitHub | `scripts/check_docs.py`, pytest |
| `backend/ringsentinel/__init__.py` | Package marker and `__version__` | Everything | none |
| `backend/ringsentinel/config.py` | `Settings` model and `get_settings()`; variant, data dir, seed | Every later stage | python-dotenv, pydantic |
| `backend/tests/test_smoke.py` | Import and version smoke test | pytest | `backend/ringsentinel/config.py` |
| `backend/tests/test_config.py` | Variant switch, defaults, overrides, validation | pytest | `backend/ringsentinel/config.py` |
| `backend/tests/test_check_docs.py` | Checker behaviour and this repo's own docs | pytest | `scripts/check_docs.py` |
| `scripts/check_docs.py` | Fails if docs name a missing path or function | CLI, CI, tests | filesystem only |
| `scripts/inspect_schema.py` | Prints real columns, value ranges, row count, SHA-256 of a raw transactions CSV and describes the patterns file; saves a report | CLI (owner runs it on the downloaded files) | standard library only |
| `backend/tests/test_inspect_schema.py` | Tests the inspector on tiny synthetic files | pytest | `scripts/inspect_schema.py` |
| `frontend/package.json` | Frontend shell, no dependencies yet | npm | none |
| `data/raw/`, `data/processed/`, `data/snapshots/` | Data folders (raw and processed are gitignored) | Later stages | none |
| `docs/ARCHITECTURE.md` | Components, principles, diagram | Humans | none |
| `docs/PROJECT_EXPLAINER.md` | This file | Humans, LLMs | none |
| `docs/STAGE_00.md` | What Stage 00 built | Humans | none |

Planned directories (created in the stage named): `backend/ringsentinel/ingest/` [planned, Stage 01], `backend/ringsentinel/graph/` [planned, Stage 02], `backend/app/` [planned, Stage 04], `backend/ringsentinel/ai/` [planned, Stage 06], `docs/DATA.md` [planned, Stage 01], `docs/EVALUATION.md` [planned, Stage 03], `docs/DIAGRAM_SPECS.md` [planned, Stage 09].

## 5. Runtime flows

Only one flow exists at Stage 00.

Loading configuration:
1. Code calls `get_settings()` in `backend/ringsentinel/config.py`.
2. It loads `.env` from the repo root if present (without overriding real environment variables).
3. It reads `RS_DATASET_VARIANT`, `RS_DATA_DIR`, `RS_SEED`; blank values count as unset.
4. It builds a `Settings` object; an unsupported variant raises a pydantic `ValidationError`.
5. Callers read `raw_dir`, `processed_dir` (per variant), and `snapshots_dir` from it.

Checking the docs:
1. `python scripts/check_docs.py` calls `main()`.
2. `find_problems()` reads README.md, HANDOVER.md and docs/*.md, extracts backticked tokens with `extract_tokens()`, and tests each with `check_token()`.
3. It prints problems and exits 1, or prints OK and exits 0.

Inspecting a raw file (Stage 01 part 1):
1. Owner runs `python scripts/inspect_schema.py` with `--trans` and `--patterns` paths.
2. `main()` calls `inspect_csv()` (one streaming pass; stats are tracked by column position) and `inspect_patterns()`.
3. `format_report()` builds the text, which is printed and saved to `data/raw/schema_report.txt` [generated].

The offline pipeline, serving a request, taking an analyst action and generating a case file are [planned].

## 6. Data contracts

No files pass between stages yet. The planned stages D1 to D13 and their outputs (all [planned]): D1 raw files plus manifest; D2 `events.parquet` with event_id, ts, src_account, dst_account, src_bank, dst_bank, amount, currency, payment_format, is_illicit, ring_id (column names to be confirmed against the real data in Stage 01); D3 derived noise columns; D4 split index; D5 graph objects and a pruning report; D6 features; D7 scores and models; D8 rings; D9 metrics, ablations, robustness, latency; D10 cases; D11 drift and replay; D12 snapshot bundle; D13 audit entries. Exact schemas are written here in the stage that creates each file.

## 7. Configuration

| Variable | Default | If wrong |
| --- | --- | --- |
| `RS_DATASET_VARIANT` | HI-Small | Anything outside HI-Small, LI-Small, HI-Medium, LI-Medium raises a validation error at startup |
| `RS_DATA_DIR` | `<repo>/data` | Pipeline reads and writes in the wrong place; point it at a folder with enough disk |
| `RS_SEED` | 42 | Non-integer values raise a ValueError; changing it changes every seeded result |

Reserved for later stages and listed in `.env.example`: Kaggle credentials, analyst token, audit database URL, LLM provider and keys.

## 8. Test map

| Test file | Guards | Failure signals |
| --- | --- | --- |
| `backend/tests/test_smoke.py` | Package imports, version string | Broken install, wrong working directory, bad `pythonpath` in `pyproject.toml` |
| `backend/tests/test_config.py` | Variant switch, per-variant output folders, blank-as-unset, validation | Medium and Small outputs could collide, or bad config accepted silently |
| `backend/tests/test_check_docs.py` | Checker catches missing paths and functions, skips planned lines; this repo's docs are consistent | A doc names something that no longer exists, or the checker regressed |
| `backend/tests/test_inspect_schema.py` | Inspector keeps repeated column names apart, counts empties, caps distinct values, flags ragged rows, makes no assumption about the patterns layout | Inspector would mislead the schema review that the ingestor depends on |

Run: `pytest` from the repo root.

## 9. Debugging playbook

| Symptom | Likely cause | Inspect | Confirm | Usual fix |
| --- | --- | --- | --- | --- |
| `ModuleNotFoundError: ringsentinel` | Running pytest outside the repo root, or `pyproject.toml` missing | `pyproject.toml` (pythonpath) | `pytest --collect-only` from the repo root | `cd` to the repo root |
| `ModuleNotFoundError: check_docs` in tests | Same cause | `pyproject.toml` | as above | as above |
| ValidationError at startup mentioning a dataset variant | Bad `RS_DATASET_VARIANT` in `.env` or the shell | `.env`; `get_settings()` in `backend/ringsentinel/config.py` | `echo %RS_DATASET_VARIANT%` in cmd | Use a supported variant |
| check_docs reports a missing path | A doc names a file that was renamed or never created | The doc line shown | `python scripts/check_docs.py` | Fix the doc, or mark the line [planned] |
| Docs checker flags something that is not a path | Backticked text looks like a path or function | `check_token()` in `scripts/check_docs.py` | run the checker on a tmp file | Remove backticks, or add [planned] |
| `ruff` import-order errors | Unsorted imports | the file shown | `ruff check .` | `ruff check . --fix` |
| CI fails on Windows only | Path separator or line-ending assumption | `.gitattributes`, the failing test | Re-run `pytest` in cmd | Use `pathlib`, avoid hard-coded `/` in code |

Order to rule out causes: environment (venv active, install done), working directory, config, then code. Logs: pytest output; CI logs on GitHub under the Actions tab.

## 10. Known issues and limits

- Nothing beyond configuration and docs tooling exists.
- Python version on the owner's machine is unconfirmed; 3.10 or newer assumed.
- CI has not been seen running on GitHub yet.
- check_docs only verifies backticked tokens in README.md, HANDOVER.md and docs/*.md. Prose is not checked.

## 11. Decision log

| Decision | Reason |
| --- | --- |
| Single dataset-variant switch with per-variant processed folders | HI-Small now, HI-Medium later without code changes or output collisions |
| Candidate rings built from real transfer edges; derived device and IP attributes used only as label-blind noise | Derived attributes are synthetic; building rings from them would make the ring structure fake |
| Every detector scored at transaction level; one shared ring extractor | Fair, like-for-like comparison with the baselines |
| Cumulative past-only graph per window | Prevents using future events when scoring a window |
| Ring recall measured on pattern-based rings only | Many laundering transactions have no pattern label, so they have no ring id |
| Pin only what the scaffold uses at Stage 00 | Avoids stale pins and install failures on an unconfirmed Python version |
| `pytest` uses `pythonpath` in `pyproject.toml` instead of an editable install | One less install step on Windows |
| LF line endings forced by `.gitattributes` | Same bytes on Windows and CI |

## 12. Glossary

- **Ring**: a group of accounts that move money in a coordinated way.
- **Hub**: a node (account or shared attribute) connected to very many others; weak evidence of coordination, so it is down-weighted or dropped.
- **IDF-style weight**: weight 1/log2(1+degree), so high-degree nodes count for less.
- **Temporal split**: train, validation and test divided by time so the test set is in the future of the training set.
- **Leakage**: information from the test period influencing training or tuning.
- **PR-AUC**: area under the precision-recall curve; compare with the share of positives.
- **Jaccard match**: overlap size divided by union size between a predicted and a true ring.
- **Net value**: ring loss caught, minus review cost, minus false-positive cost.
- **PSI**: population stability index, a drift measure.
- **Snapshot**: a precomputed JSON file the UI can read without the backend.
- **Variant**: which IBM AML file set is in use (HI/LI by Small/Medium).
- **HI / LI**: higher / lower illicit ratio versions of the IBM synthetic data.

## 13. How to regenerate every artifact

Windows cmd, repo root:

```
py -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
pytest
ruff check .
python scripts\check_docs.py
```

Data and model artifacts: [planned] (`scripts/reproduce.py` [planned] from Stage 03).
