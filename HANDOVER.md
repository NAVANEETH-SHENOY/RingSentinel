# HANDOVER (end of Stage 03 build; read before continuing in a new chat)

## Summary

Plain language: RingSentinel will help fraud analysts find and review groups of accounts that move money like a coordinated ring, with honest measurement and a human making every decision. So far the project loads the public IBM synthetic money-laundering data, labels the known rings, splits the data by time, builds the account graph with hub control, and (new in Stage 03) scores every transfer with four detectors, groups flagged transfers into candidate rings, and measures everything on a held-out test period including the rupee cost of false alarms. **The Stage 03 measuring code has never been run on the real data, so there are no results yet.**

Technical: Stage 01 (D1/D2/D4 plus two baselines) and Stage 02 (D3 noise layer, D5 graph, D6 features) are unchanged. Stage 03 adds D7 (velocity rule, tabular XGBoost, graph-feature XGBoost, Isolation Forest; a `SplitVault` that releases the test split once per detector), D8 (rings from the flagged subgraph) and D9 (transaction and ring metrics, Jaccard match, net-value cost model with a 36-setting sweep, ablation, edge-dropout robustness, latency, `scripts/reproduce.py`).

## Architecture and key decisions

See `docs/ARCHITECTURE.md`, `docs/EVALUATION.md` and the decision log in `docs/PROJECT_EXPLAINER.md`. The ones to remember:
- Terminal: Windows cmd (git commands in Git Bash). Python 3.13.3 on the owner's machine.
- Dataset: IBM AML HI-Small by default; `RS_DATASET_VARIANT` switches variant; HI-Medium never tried.
- Labels from the CSV `Is Laundering` column (5,177 positives); ring truth from the patterns file covers 3,209 of them (370 rings). Ring metrics are on pattern rings only.
- Protocol: fit on train; early stopping and all thresholds on validation; test scored once per detector. Two operating points: validation-best F1 and validation-best net value.
- Rupee defaults (accepted by the owner, with rationale in `docs/EVALUATION.md`): INR 250 per ring review, INR 500 per legitimate account wrongly inside a flagged ring, capture rate 1.0, plus a sensitivity sweep. They are planning assumptions. FX rates in `config/fx_rates_inr.json` are placeholders.
- Stage 03 code depends only on the parquet contracts, not on Stage 01 Python modules (they were not in the incremental Stage 02 zip), so the Stage 03 baselines are re-implemented and are not byte-identical with Stage 01's.
- New dependency: `joblib==1.6.0` pinned (already a scikit-learn dependency). networkx still unused.

## Milestone status

| Milestone | Stage | Status |
| --- | --- | --- |
| M0 | 00 scaffold | Done (owner: 16 passed) |
| M1 | 01 data and baselines | Done; owner ran it on the real corrected HI-Small (85 passed); tag v0.2.0 |
| M2 | 02 graph and features | Built; builder ran every step on the real files. Owner's test output and the v0.3.0 tag were not seen by the Stage 03 builder |
| M3 | 03 detectors and evaluation | Built and tested on synthetic data in the sandbox. Real-data run, owner's test run, merge and tag v0.4.0 pending |
| M4 to M9 | 04 to 09 | Not started |

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
python scripts\run_stage01.py
python scripts\run_stage02.py
python scripts\run_stage03.py
python scripts\reproduce.py
```

Raw files go in `data\raw`: HI-Small_Trans.csv and HI-Small_Patterns.txt. Run `python scripts\reproduce.py` twice; the second run should print REPRODUCED.

## Environment variable names

The names are: `RS_DATASET_VARIANT`, `RS_DATA_DIR`, `RS_SEED`, `RS_TRAIN_FRAC`, `RS_VAL_FRAC`, `RS_HUB_CAP`, `RS_ATTR_CAP`, `RS_COMMUNITY_CAP`, `RS_LOUVAIN_RESOLUTION`, `RS_NEG_SAMPLE_FRAC`, `RS_REVIEW_COST_INR`, `RS_FP_COST_INR`, `RS_LOSS_CAPTURE_RATE`, `RS_RING_TAU`, `RS_RING_MIN_SIZE`. Reserved for later: `KAGGLE_USERNAME`, `KAGGLE_KEY`, `RS_ANALYST_TOKEN`, `RS_AUDIT_DB_URL`, `RS_LLM_PROVIDER`, `GROQ_API_KEY`, `GEMINI_API_KEY`. The owner has Groq for development and Gemini for production, with no keys in the project yet.

## Test status (real results only)

- Owner, Windows, Python 3.13.3 (Stage 01, 12 Nov 2026): `pytest` 85 passed, ruff clean, check_docs OK.
- Builder, Linux sandbox (Python 3.13, pinned requirements), Stage 03: `pytest --ignore=backend/tests/test_stage02_pipeline.py` gave **117 passed** (50 earlier tests that run without Stage 01 sources, plus 67 new Stage 03 tests). `ruff check .` clean with the builder's own config (rules E, F, B, UP, line length 100; the project's real ruff config was not available, so import-order rules were not checked).
- **NOT EXECUTED by the builder**: the Stage 01 tests and `backend/tests/test_stage02_pipeline.py` (they need Stage 01 sources and `backend/tests/conftest.py`, which were not in the zip); the real `scripts/check_docs.py` (a stand-in script was used and only the new Stage 03 docs were examined); the whole Stage 03 stage on the real data; CI on GitHub (never observed); Windows installs of the pinned packages.
- Owner's Stage 03 run: NOT EXECUTED.

## Dataset citations and licence status

IBM AML (Altman et al., NeurIPS 2023 Datasets and Benchmarks): authors, title and venue confirmed on the NeurIPS proceedings page; page numbers, URL form and BibTeX not verified. Licence: the paper's supplement says "Community Data License Agreement"; the exact variant and its terms are NOT verified. Elliptic is not used yet (licence unchecked).

## Known bugs, caveats, open questions

- Everything about Stage 03 on real data is unknown: run time, memory, results. The ring-extraction sweeps (about 80 extractions per detector) are the likely slow part.
- At capture rate 1.0 the net-value rule may drift toward flagging everything with an illicit hit (amounts are synthetic and can be huge); read the cost sweep, not just the headline.
- Strict ring precision is pessimistic (real laundering outside pattern rings counts as a false ring); `lenient_precision` is reported beside it.
- The Stage 03 velocity rule and tabular XGBoost differ from Stage 01's; `data/processed/hi_small/detect_report.json` [generated] holds the Stage 01 numbers for comparison. Do not mix them in one table.
- 1,968 of 5,177 positives belong to no ring; the positive rate rises across splits (0.075, 0.107, 0.177 percent).
- XGBoost can differ slightly between Windows and Linux; quote the platform.
- Validation numbers are optimistic by construction.
- The velocity rule scored at chance on validation in Stage 01; communities do not recover rings; hub control only trims the giant component by 6 to 8 points. These are the documented negative findings so far. A Stage 03 negative finding must still be added to `docs/EVALUATION.md` after the real run.
- `config/fx_rates_inr.json` rates are approximate placeholders; replace or accept them before quoting rupee figures.
- Features are window-level (retrospective); detection latency is a lower bound.
- Timestamps run to 18 Sep although the data is described as 10 days.
- CI never observed on GitHub.

## Pending from the owner before Stage 04 starts

1. Apply the Stage 03 zip, `pip install -r requirements.txt`, run `pytest`, `ruff check .`, `python scripts\check_docs.py`; paste the outputs. Report any ruff import-order complaints.
2. Run `python scripts\reproduce.py` twice on the real data; paste the console output of both runs and send `docs\EVALUATION_RESULTS.md`, `data\processed\hi_small\metrics.json` and `data/processed/hi_small/detect_report.json`. Report run time and peak memory if you notice them.[generated]
3. Git (Git Bash): branch `stage-03-detectors-evaluation`, commit, push, PR, merge, tag v0.4.0. Confirm Stage 02's tag v0.3.0 exists.
4. Replace or accept the placeholder FX rates; confirm the buildathon deadline.

## Next: Stage 04 (snapshots and backend, after the real Stage 03 numbers are frozen)

Build the snapshot exporter (D12) and FastAPI backend (D13, C11, C12): `scripts/export_snapshots.py`, `backend/ringsentinel/snapshots/` [planned], `backend/app/` [planned] (main, routes, audit, config), JSON schema for the bundle, hash-chained SQLite audit log, endpoints health, queue, case, metrics, drift, replay, action, audit, audit verify; rate limiting and CORS. It reads `rings.json` [generated], `metrics.json` [generated], `latency.json` [generated], `ablations.json` [generated], `robustness.json` [generated]. Files to touch: `requirements.txt` (fastapi, uvicorn, httpx for tests; pin them), `.env.example` (RS_ANALYST_TOKEN, RS_AUDIT_DB_URL), `docs/ARCHITECTURE.md`, `docs/PROJECT_EXPLAINER.md`, `README.md`, `CHANGELOG.md`, `HANDOVER.md`.

## Continue-from-here prompt (paste into a new chat, with the project zip and this file attached)

```
You are my pair-programmer on RingSentinel (Razorpay AI Buildathon, Track 02, defense-only). First read HANDOVER.md, docs/PROJECT_EXPLAINER.md and docs/EVALUATION.md from the attached project zip, then follow the stage rules in the project instructions (prerequisites first, incremental zip with CHANGES_STAGE_NN.md containing only added or modified files, exact cmd commands, tests marked PASSED only if actually run here else NOT EXECUTED, docs and explainer updated, git workflow, caveats at the end).
State: Stages 00 to 03 are built; v0.2.0 tagged; v0.3.0 and v0.4.0 once I confirm (check git). Stage 03 has not been confirmed on the real data until I paste the reproduce.py output and docs/EVALUATION_RESULTS.md. Wait for me to say "begin Stage 04", unless I paste the Stage 03 results first, in which case help me write the Stage 03 findings (including a negative one) into docs/EVALUATION.md.
Environment: Windows, cmd for everything except git (Git Bash), Python 3.13.3, dataset HI-Small (keep code switchable to HI-Medium). Your sandbox cannot reach Kaggle; rely on the files in the zip or on what I paste. The incremental zips do not contain earlier stages' source files: ask me for any file you need rather than guessing its signatures.
```
