# HANDOVER (end of Stage 01 build; read before continuing in a new chat)

## Summary

Plain language: RingSentinel will help fraud analysts find and review groups of accounts that move money like a coordinated ring, with honest measurement and a human making every decision. So far the project loads the public IBM synthetic money-laundering data, labels the known rings, splits the data by time, and scores two simple baseline detectors.

Technical: Python pipeline stage D1/D2/D4 (checksum manifest, chunked ingest to a typed parquet event table, pattern-derived labels, time split with ring assignment) plus two baselines (24-hour velocity rule, tabular XGBoost) evaluated on the validation split only, with shared metrics. No graph, API or UI yet.

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
| M1 | 01 data and baselines | Pipeline run on the real corrected HI-Small by the owner (pytest 82 passed, ruff clean, check_docs OK); builder reproduced 82 passed on the same files. Git commit, PR, merge and tag v0.2.0 still pending |
| M2 to M9 | 02 to 09 | Not started |

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
```

Raw files go in `data\raw`: HI-Small_Trans.csv and HI-Small_Patterns.txt.

## Environment variable names

`RS_DATASET_VARIANT`, `RS_DATA_DIR`, `RS_SEED`, `RS_TRAIN_FRAC`, `RS_VAL_FRAC`. Reserved for later: `KAGGLE_USERNAME`, `KAGGLE_KEY`, `RS_ANALYST_TOKEN`, `RS_AUDIT_DB_URL`, `RS_LLM_PROVIDER`, `GROQ_API_KEY`, `GEMINI_API_KEY`. The owner has Groq for development and Gemini for production, but has no keys in the project yet.

## Test status (real results only)

- Owner, Windows, Python 3.13.3, real files in `data\raw` (12 Nov 2026): `pytest` 82 passed, ruff all checks passed, check_docs 7 files OK; `scripts\run_stage01.py` completed (see the numbers in `docs/STAGE_01.md`).
- Builder, Linux, same real files from the owner's zip: `pytest` 82 passed before the label-note fix; after it, see the final run in the builder's reply. Ruff and check_docs were run again after the edits.
- NOT EXECUTED: CI on GitHub; any run of HI-Medium.

## Dataset citations and licence status

IBM AML (Altman et al., NeurIPS 2023 Datasets and Benchmarks): authors, title and venue confirmed on the NeurIPS proceedings page; page numbers, URL form and BibTeX not verified. Licence: the paper's supplement says "Community Data License Agreement"; the exact variant and its terms are NOT verified. Elliptic is not used yet (licence unchecked).

## Known bugs, caveats, open questions

- 1,968 of 5,177 positives belong to no ring: report ring recall on pattern rings only and say so next to every ring metric.
- Positive rate rises across the split (0.075, 0.107, 0.177 percent): state it beside the Stage 03 test results.
- XGBoost validation PR-AUC differs by platform (0.0707 Windows, 0.0688 Linux); same-machine reruns are identical. Quote one platform's numbers and say which.
- The velocity rule scores at chance on validation (PR-AUC 0.00102 vs prevalence 0.00107): keep it as a documented negative finding, do not tune it on test.
- `config/fx_rates_inr.json` rates are approximate placeholders; the owner should replace them or accept them before rupee figures are reported.
- Node identity for the graph: account string alone vs bank plus account. The ingest report counts accounts seen with more than one bank; decide from that number in Stage 02.
- Timestamps run to 18 Sep although the data is described as 10 days; they fall into the test split.
- Validation baseline numbers are optimistic by construction (threshold and early stopping on validation).
- CI never observed on GitHub.

## Pending from the owner before Stage 02 starts

1. After applying the label-fix zip: rerun `pytest`, `ruff check .`, `python scripts\check_docs.py`, then `python scripts\run_stage01.py --step baselines` so `baseline_metrics.json` [generated] carries the corrected label note. Expect 85 passed (82 plus 3 new tests).
2. Git: commit the Stage 01 work in small commits, push `stage-01-data-baselines`, open or update the PR, merge, tag v0.2.0.
3. The licence line and citation text from the Kaggle dataset page (optional but wanted).
4. Answer the Stage 02 decisions listed below (node identity, hub degree cap).

## Next: Stage 02 (graph and features), after the above is confirmed

Build D3, D5, D6: label-blind noise layer (device, IP, VPA-style attributes, fixed seed, marked derived); transfer graph with IDF-style edge weight on counterparty degree and a degree cap; cumulative past-only graph per split window; community detection; node and community features with bounded cycle search; pruning report; script showing giant-component size with and without hub control. [planned] Files to add: `backend/ringsentinel/graph/` (build, hubs, communities), `backend/ringsentinel/features/`, `backend/ringsentinel/noise.py`, `scripts/ablation_giant_component.py`, tests, `docs/STAGE_02.md`. Files to touch: `requirements.txt` (networkx, scipy pinned), `docs/PROJECT_EXPLAINER.md`, `docs/ARCHITECTURE.md`, `CHANGELOG.md`, `HANDOVER.md`. Decisions to make first: node identity (see above) and hub degree cap value (chosen on validation only).

## Continue-from-here prompt (paste into a new chat, with the project zip and this file attached)

```
You are my pair-programmer on RingSentinel (Razorpay AI Buildathon, Track 02, defense-only). First read HANDOVER.md and docs/PROJECT_EXPLAINER.md from the attached project zip, then follow the stage rules in the project instructions (prerequisites first, incremental zip with CHANGES_STAGE_NN.md, exact cmd commands, tests marked PASSED only if actually run here else NOT EXECUTED, docs and explainer updated, git workflow, caveats at the end).
State: Stage 00 and Stage 01 are done and tagged v0.2.0 (confirm in git before starting). Labels come from the CSV `Is Laundering` column; rings come from the patterns file. Wait for me to say "begin Stage 02".
Environment: Windows, cmd for everything except git (Git Bash), Python 3.13.3, dataset HI-Small (keep code switchable to HI-Medium). Your sandbox cannot reach Kaggle; rely on the files in the zip or on what I paste.
```
