# HANDOVER (end of Stage 02 build; read before continuing in a new chat)

## Summary

Plain language: RingSentinel will help fraud analysts find and review groups of accounts that move money like a coordinated ring, with honest measurement and a human making every decision. So far the project loads the public IBM synthetic money-laundering data, labels the known rings, splits the data by time, scores two simple baseline detectors, and builds the account graph with hub control plus per-account and per-community features.

Technical: Python pipeline stage D1/D2/D4 (checksum manifest, chunked ingest to a typed parquet event table, pattern-derived labels, time split with ring assignment) plus two baselines (24-hour velocity rule, tabular XGBoost) evaluated on the validation split only, with shared metrics. Stage 02 adds D3 (label-blind synthetic noise layer), D5 (cumulative past-only transfer graph per window, IDF edge weights, validation-tuned degree cap, igraph Louvain communities) and D6 (features). No graph detector, ring extraction, API or UI yet.

## Architecture and key decisions

See `docs/ARCHITECTURE.md` and the decision log in `docs/PROJECT_EXPLAINER.md`. The ones to remember:
- Terminal: Windows cmd (git commands in Git Bash). Python 3.13.3 on the owner's machine.
- Dataset: IBM AML HI-Small by default; one setting (`RS_DATASET_VARIANT`) switches variant and the code is written to run HI-Medium (not yet tried).
- The corrected CSV has an `Is Laundering` column (5,177 positives) and it is the label source. The patterns file gives ring structure for only 3,209 of them (370 rings), so 1,968 positives belong to no known ring (`docs/DATA.md`). A 10-column file is still accepted as a fallback.
- All ids are text. Amounts are parsed with Python float on both sides of the label match.
- The test split is removed before any baseline feature or fit; no test-split result exists yet.
- Approved plan changes: rings from real transfer edges with IDF-style weight on counterparty degree; all detectors scored per transaction; cumulative past-only graph per window; ring recall on pattern rings only; Isolation Forest in Stage 03; GraphSAGE dropped.

## Milestone status

| Milestone | Stage | Status |
| --- | --- | --- |
| M0 | 00 scaffold | Done. Owner ran pytest, ruff, check_docs on Windows: 16 passed |
| M1 | 01 data and baselines | Done. Owner ran it on the real corrected HI-Small (85 passed); pushed; tag v0.2.0 |
| M2 | 02 graph and features | Built. Builder ran every step on the real files (132 tests passed, ruff clean, check_docs OK). Owner's run, merge and tag v0.3.0 pending |
| M3 to M9 | 03 to 09 | Not started |

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
python scripts\ablation_giant_component.py
```

Raw files go in `data\raw`: HI-Small_Trans.csv and HI-Small_Patterns.txt.

## Environment variable names

`RS_DATASET_VARIANT`, `RS_DATA_DIR`, `RS_SEED`, `RS_TRAIN_FRAC`, `RS_VAL_FRAC`, `RS_HUB_CAP`, `RS_ATTR_CAP`, `RS_COMMUNITY_CAP`, `RS_LOUVAIN_RESOLUTION`. Reserved for later: `KAGGLE_USERNAME`, `KAGGLE_KEY`, `RS_ANALYST_TOKEN`, `RS_AUDIT_DB_URL`, `RS_LLM_PROVIDER`, `GROQ_API_KEY`, `GEMINI_API_KEY`. The owner has Groq for development and Gemini for production, but has no keys in the project yet.

## Test status (real results only)

- Owner, Windows, Python 3.13.3 (Stage 01, 12 Nov 2026): `pytest` 85 passed, ruff clean, check_docs OK, `scripts\run_stage01.py` completed.
- Builder, Linux, real files from the owner's zip (Stage 02): `pytest` 132 passed, ruff clean, check_docs OK; every Stage 02 step ran on the real data (numbers in `docs/STAGE_02.md`).
- Owner's Stage 02 run: NOT EXECUTED. CI on GitHub never observed. HI-Medium never run.

## Dataset citations and licence status

IBM AML (Altman et al., NeurIPS 2023 Datasets and Benchmarks): authors, title and venue confirmed on the NeurIPS proceedings page; page numbers, URL form and BibTeX not verified. Licence: the paper's supplement says "Community Data License Agreement"; the exact variant and its terms are NOT verified. Elliptic is not used yet (licence unchecked).

## Known bugs, caveats, open questions

- 1,968 of 5,177 positives belong to no ring: report ring recall on pattern rings only and say so next to every ring metric.
- Positive rate rises across the split (0.075, 0.107, 0.177 percent): state it beside the Stage 03 test results.
- XGBoost validation PR-AUC differs by platform (0.0707 Windows, 0.0688 Linux); same-machine reruns are identical. Quote one platform's numbers and say which.
- The velocity rule scores at chance on validation (PR-AUC 0.00102 vs prevalence 0.00107): keep it as a documented negative finding, do not tune it on test.
- `config/fx_rates_inr.json` rates are approximate placeholders; the owner should replace them or accept them before rupee figures are reported.
- Stage 02 negative finding: Louvain communities do not recover rings (median best Jaccard about 0.04). Ring candidates must come from the scored subgraph (Stage 03); plan section 5.3 as written does not work on this data.
- Hub control trims the giant component only about 6 to 8 points; about 98 percent of validation ring accounts sit inside it. Say so in the README.
- Features are window-level (they may use later events inside the same window); the hub cap rule uses validation labels; derived attributes are synthetic.
- igraph replaces networkx for Louvain (networkx took over five minutes on the real data); networkx is not pinned yet.
- Timestamps run to 18 Sep although the data is described as 10 days; they fall into the test split.
- Validation baseline numbers are optimistic by construction (threshold and early stopping on validation).
- CI never observed on GitHub.

## Pending from the owner before Stage 03 starts

1. Apply the Stage 02 zip, `pip install -r requirements.txt`, run `pytest`, `ruff check .`, `python scripts\check_docs.py`, `python scripts\run_stage02.py`, `python scripts\ablation_giant_component.py`; paste the outputs.
2. Git (Git Bash): branch `stage-02-graph-features`, commit, push, PR, merge, tag v0.3.0.
3. Rupee assumptions for the cost model (review cost, false-positive cost) or accept defaults; the buildathon deadline.

## Next: Stage 03 (detectors, ring extraction, evaluation)

Build graph-feature XGBoost on `features.parquet` (D6), Isolation Forest, one shared ring extractor over the flagged subgraph, ring-level Jaccard match (pattern rings only), the net-value cost model, and the test-split evaluation. [planned] Files to add: `backend/ringsentinel/detect/`, `backend/ringsentinel/rings/`, `backend/ringsentinel/evaluate/`, `scripts/run_stage03.py`, tests, `docs/STAGE_03.md`, `docs/EVALUATION.md`. Files to touch: `requirements.txt` (networkx if used), `docs/PROJECT_EXPLAINER.md`, `docs/ARCHITECTURE.md`, `README.md`, `CHANGELOG.md`, `HANDOVER.md`.

## Continue-from-here prompt (paste into a new chat, with the project zip and this file attached)

```
You are my pair-programmer on RingSentinel (Razorpay AI Buildathon, Track 02, defense-only). First read HANDOVER.md and docs/PROJECT_EXPLAINER.md from the attached project zip, then follow the stage rules in the project instructions (prerequisites first, incremental zip with CHANGES_STAGE_NN.md, exact cmd commands, tests marked PASSED only if actually run here else NOT EXECUTED, docs and explainer updated, git workflow, caveats at the end).
State: Stages 00 to 02 are built; v0.2.0 tagged, v0.3.0 once I confirm (check git). Stage 02 produced features.parquet (D6); communities do not recover rings, so rings are extracted after scoring. Labels come from the CSV `Is Laundering` column; rings come from the patterns file. Wait for me to say "begin Stage 03".
Environment: Windows, cmd for everything except git (Git Bash), Python 3.13.3, dataset HI-Small (keep code switchable to HI-Medium). Your sandbox cannot reach Kaggle; rely on the files in the zip or on what I paste.
```
