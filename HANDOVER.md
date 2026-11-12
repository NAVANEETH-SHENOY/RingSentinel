# HANDOVER (end of Stage 00)

## Summary

Plain language: RingSentinel will help fraud analysts find and review groups of accounts that move money like a coordinated ring, with honest measurement and a human making every decision. Stage 00 delivered only the tested skeleton.

Technical: Python backend scaffold with a validated settings module (single dataset-variant switch), a docs-consistency checker, tests, lint, CI. No detection code yet.

## Architecture and key decisions

See `docs/ARCHITECTURE.md` and the decision log in `docs/PROJECT_EXPLAINER.md`.

## Milestone status

| Milestone | Stage | Status |
| --- | --- | --- |
| M0 | 00 scaffold | Built. Owner confirmation of tests on Windows pending |
| M1 to M9 | 01 to 09 | Not started |

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
```

## Environment variable names

`RS_DATASET_VARIANT`, `RS_DATA_DIR`, `RS_SEED`. Reserved later: `KAGGLE_USERNAME`, `KAGGLE_KEY`, `RS_ANALYST_TOKEN`, `RS_AUDIT_DB_URL`, `RS_LLM_PROVIDER`, `GROQ_API_KEY`, `GEMINI_API_KEY`.

## Test status

Executed in the build environment (Linux, Python 3.13): see `docs/STAGE_00.md` and the Stage 00 reply for the exact output. Not yet run on the owner's Windows machine or on GitHub Actions.

## Dataset citations and licence status

None used yet. Stage 01 will record them in `docs/DATA.md` [planned] after checking the source pages. Not to be filled from memory.

## Known bugs, caveats, open questions

- Python version on the owner's machine unconfirmed (3.10+ assumed).
- CI untested on GitHub.
- Open for Stage 01: exact IBM AML file names and columns, licence text, currency handling, timestamp format.

## Next: Stage 01 (data, temporal split and baselines)

Files to add: `backend/ringsentinel/ingest/` [planned], `backend/ringsentinel/splitter.py` [planned], `backend/ringsentinel/models/baselines.py` [planned], `backend/ringsentinel/evaluation/metrics.py` [planned], `docs/DATA.md` [planned], `data/raw/MANIFEST.json` [planned], plus tests. Requires a Kaggle API token and acceptance of the dataset terms.

## Continue-from-here prompt (paste into a new chat with the project zip)

```
You are my pair-programmer on RingSentinel (Razorpay AI Buildathon, Track 02, defense-only). Read docs/PROJECT_EXPLAINER.md and HANDOVER.md in the attached zip first. Stage 00 is complete (v0.1.0). Terminal: Windows cmd (git commands in Git Bash). Dataset: IBM AML HI-Small by default, with the code kept switchable to HI-Medium. Follow the project's stage-by-stage rules: prerequisites first, an incremental zip, tests with honest PASSED or NOT EXECUTED status, docs updated, git workflow, and caveats at the end. Begin only when I say "begin Stage 01".
```
