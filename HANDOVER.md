# HANDOVER (end of Stage 09 build, release v1.0.0; read before continuing in a new chat)

## Stage 09 summary (read this first)

Plain language: Stage 09 makes RingSentinel deployable and finishes the paperwork. The decision log can now live in Postgres (because free hosting erases its disk), there are files to put the API on Render, the site on Vercel and the log on Neon, a script that checks the live site, a finished README with the real results and honest limitations, three diagram specs, and a voice-over script for the demo.

Technical: `backend/app/audit_pg.py` (Postgres store; advisory lock; per-operation connections; `AuditUnavailable` to 503 + `Retry-After`), `open_audit_log`/`backend_of` in `backend/app/audit.py`, the liveness route and `audit_backend` in `backend/app/routes.py`, `requirements-api.txt` (slim runtime set), `render.yaml`, `frontend/vercel.json`, `scripts/smoke_deployed.py`, `scripts/sync_readme_results.py`, a label fix in `frontend/src/components/CaseView.tsx`. One new dependency: `psycopg[binary]==3.3.9`.

### Test status (real results, builder's Linux sandbox; not yet run by the owner)

- Backend with `RS_TEST_POSTGRES_URL` set to local Postgres 16: 733 passed, 8 skipped. Without it: 721 passed, 20 skipped.
- Frontend: 122 passed. `ruff check .` clean. `python scripts/check_docs.py` OK. `python scripts/secrets_scan.py`: nothing found.
- Live: API from `requirements-api.txt` + local Postgres + built static site + real bundle: `scripts/smoke_deployed.py` 44 passed, 0 failed, 1 warning (not frozen).
- **NOT EXECUTED anywhere:** Render, Vercel, Neon, GitHub Actions (the new `postgres-audit` and `smoke-deployed` jobs), Windows, the real-data pipeline in this stage.

### What you must do next, in order

1. Unzip the Stage 09 zip over your repo; run the setup block below and `pytest`; paste the output back if anything fails.
2. Confirm the IBM licence line on the Kaggle page (the committed bundle is derived data; CDLA-Sharing-1.0 is reported) and fill the citation details marked "verify" in `docs/DATA.md`.
3. Freeze: `python scripts\export_snapshots.py --frozen --git-commit <short sha>`, then `python scripts\sync_frontend_snapshots.py`. Commit `data\snapshots` and `frontend\public\snapshots`.
4. Create the Neon project, the Render Blueprint and the Vercel project exactly as in `docs/DEPLOYMENT.md`; then run the smoke test. Fix every FAIL.
5. Check `RS_TRUSTED_PROXY_HOPS` (inferred value 2) as described in `docs/DEPLOYMENT.md`.
6. Add the live URLs to the README status line; retake screenshots if you want the unfrozen banner gone; record the demo with `docs/DEMO_SCRIPT.md`.
7. Merge, tag v1.0.0, push.

### Open items and risks

- Hosting behaviour is from public docs and inference only. Neon's pooled string is untested; use the direct one.
- Licences: IBM CDLA-Sharing-1.0 (confirm; derived data is committed); Elliptic CC BY-NC-ND 4.0; Vercel Hobby non-commercial; the Groq key shared in an earlier zip must be revoked (Stage 08 note).
- Scientific caveats stay in the README "Limitations": synthetic data, one seed, no intervals, placeholder FX, degenerate net value at capture 1.0, hub control not an accuracy gain, 1 of 500 case files from a real model, feedback rule unvalidated.
- If you want to continue after v1.0.0, candidate work (none started): confidence intervals over several seeds; a real-model evaluation of the AI layer; individual analyst accounts; validation of the feedback rule; fixing the replay triangle-label overlap in `frontend/src/components/ReplayView.tsx`.

### Ready-to-paste "continue from here" prompt

> I am continuing RingSentinel (Razorpay AI Buildathon, Track 02, defense-only), solo, Windows cmd terminal (git in Git Bash). Stage 09 / v1.0.0 is built: Postgres audit store (`backend/app/audit_pg.py`), deployment files (`render.yaml`, `requirements-api.txt`, `frontend/vercel.json`), `scripts/smoke_deployed.py`, generated README tables, final docs, `docs/DEMO_SCRIPT.md`. Read `HANDOVER.md`, `docs/STAGE_09.md` and `docs/PROJECT_EXPLAINER.md` first. Rules: incremental zips with only new or changed files plus CHANGES_STAGE_NN.md; say "passed" only for tests actually run, otherwise "NOT EXECUTED"; flag deviations; never fabricate; no Co-Authored-By line and no links in commit messages or PR descriptions. I have done: [fill in: tests run / deployed / smoke result / frozen / tagged]. Today I want: [fill in].

---

Stage 08 (Elliptic second dataset, optional GraphSAGE, API hardening, secrets and dependency review; `docs/STAGE_08.md`) is built on the owner's Stage 07 repository. Stage 07 below is unchanged in behaviour.

Stage 07 is built on the owner's merged Stage 06 repository (main at f42a7e2, with the owner's Groq provider changes and the owner's `AiCard` in `frontend/src/components/CaseView.tsx`). The zip contains only Stage 07 files.

## Summary

Plain language: RingSentinel helps fraud analysts review groups of accounts that move money like a coordinated ring. Stages 01 to 04 load the public IBM synthetic data, build the account graph, score transfers with four detectors, group flagged transfers into candidate rings, measure everything on a held-out test period (with the rupee cost of false alarms) and package results into a checked bundle served by a local API with a tamper-evident decision log. Stage 05 is the web interface. Stage 06 adds an AI-written case file per ring that is checked against the ring's own transfers and never changes a score. New in Stage 07: analysts confirm, dismiss or hold a ring from the case page; repeated dismissals nudge a bounded threshold and the queue can be re-ranked live (reversible, because it is computed from the log); a Drift page shows whether score distributions shift over time; the Replay page shows when each ring would have been caught.

Technical: new packages `backend/ringsentinel/review/` (feedback rule: `offset = clamp(step*(dismissed - w*confirmed), 0, max_offset)` in log-odds; effective threshold = sigmoid(logit(base)+offset); adjusted score = sigmoid(logit(score)-offset); stored scores never change) and `backend/ringsentinel/monitor/` (drift module: PSI over reference-quantile bins, per equal-width time window, warn 0.10, alert 0.25, "insufficient" below 500 events; replay module: retrospective detection time = when a ring's transfers first touch `RS_RING_MIN_SIZE` accounts; truth latency only when one true ring supplies at least 50 percent of the transfers). API: `GET /api/v1/queue?order=export|live`, `GET /api/v1/feedback`. Exporter embeds drift and replay (`--no-monitor` skips). Frontend: `ActionPanel`, `FeedbackCard`, `AiCard`, `DriftView`, `ReplayView` (slider), Drift page. No new dependency.

## Architecture and key decisions

See `docs/ARCHITECTURE.md`, `docs/STAGE_04.md`, `docs/STAGE_07.md`, `docs/EVALUATION.md` and the decision log in `docs/PROJECT_EXPLAINER.md`. Key points:
- Terminal: Windows cmd (git in Git Bash). Python 3.13.3 on the owner's machine; CI uses 3.11. Node 22.12 or newer.
- Feedback is unvalidated (`validated: false`): a bounded heuristic, not a learned model. Hard ceilings step 1.0, max offset 3.0, weight 5.0. Holds are neutral; confirmations only cancel dismissals.
- Drift reference is the validation split (deviation from the plan's "training distribution", because training scores are fitted). Replay is retrospective, not a streaming simulation.
- Audit log, token, idempotency and status rules as in Stage 04: pending to any action; held to confirm or dismiss; decided is closed (409). Action route `POST /api/v1/cases/{ring_id}/action`: 201 new, 200 with `replayed: true` on a repeat.
- Queue order `EV = score x capture x amount_inr - review - fp x n_members x (1 - score)` is a heuristic on an uncalibrated score.
- The LLM only explains; everything it cites is verified; template fallback on any failure.
- Earlier decisions (dataset, protocol, rupee defaults, bundle contract, light-mode UI) are unchanged; see the explainer.

## Milestone status

| Milestone | Stage | Status |
| --- | --- | --- |
| M0 | 00 scaffold | Done |
| M1 | 01 data and baselines | Done, tag v0.2.0 |
| M2 | 02 graph and features | Built; builder ran on real files; owner output and v0.3.0 not seen |
| M3 | 03 detectors and evaluation | Run on the real HI-Small data by the owner (results in `docs/EVALUATION_RESULTS.md`); tag status not seen |
| M4 | 04 snapshots and backend | In the owner's repo |
| M5 | 05 frontend core | Merged in the owner's repo (PR #5) |
| M6 | 06 AI layer | Merged in the owner's repo (PR #6), with the owner's Groq changes; the owner says everything works after fixing the Groq call handling (output not seen by the builder) |
| M7 | 07 HITL, feedback, drift, replay | Built and tested in the sandbox; owner's run, merge and tag v0.8.0 pending |
| M8 | 08 Elliptic, hardening | Built; the owner has since run Elliptic on the real files (docs/DATA.md records 15 Nov 2026); merge and tag v0.9.0 status not seen |
| M9 | 09 deploy, docs, demo | Built and tested in the sandbox; hosting not exercised; owner's run, deployment, smoke test, freeze, merge and tag v1.0.0 pending |

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
python scripts\export_snapshots.py
python scripts\run_api.py
cd frontend
npm ci
npm run check
npm run build
npm run dev
```

Demo without real data: `python scripts\make_demo_bundle.py` then `python scripts\sync_frontend_snapshots.py`. Set `RS_ANALYST_TOKEN` (16+ characters) in `.env` before taking actions. API docs: http://127.0.0.1:8000/api/docs.

## Environment variable names

The names are: `RS_DATASET_VARIANT`, `RS_DATA_DIR`, `RS_SEED`, `RS_TRAIN_FRAC`, `RS_VAL_FRAC`, `RS_HUB_CAP`, `RS_ATTR_CAP`, `RS_COMMUNITY_CAP`, `RS_LOUVAIN_RESOLUTION`, `RS_NEG_SAMPLE_FRAC`, `RS_REVIEW_COST_INR`, `RS_FP_COST_INR`, `RS_LOSS_CAPTURE_RATE`, `RS_RING_TAU`, `RS_RING_MIN_SIZE`, `RS_GIT_COMMIT`, `RS_SNAPSHOT_DIR`, `RS_ANALYST_TOKEN`, `RS_AUDIT_DB_URL`, `RS_CORS_ORIGINS`, `RS_RATE_LIMIT_READ_PER_MIN`, `RS_RATE_LIMIT_WRITE_PER_MIN`. Stage 06 adds `RS_LLM_PROVIDER`, `RS_LLM_MODEL`, `RS_LLM_TIMEOUT_S`, `RS_LLM_MIN_INTERVAL_S`, `RS_LLM_MAX_TOOL_CALLS`, `RS_LLM_VERIFY_RETRIES`, `RS_AI_MAX_LLM_CASES`, `GROQ_API_KEY`, `GEMINI_API_KEY`. Reserved for later: `KAGGLE_USERNAME`, `KAGGLE_KEY`. Stage 07 adds `RS_FEEDBACK_STEP`, `RS_FEEDBACK_MAX_OFFSET`, `RS_FEEDBACK_CONFIRM_WEIGHT`, `RS_PSI_WARN_LEVEL`, `RS_PSI_ALERT_LEVEL`, `RS_DRIFT_WINDOWS`, `RS_DRIFT_BINS`, `RS_DRIFT_MIN_EVENTS`, `RS_REPLAY_STEPS` (defaults in `.env.example`). The owner has Groq for development and Gemini for production, with no keys in the project yet.

## Test status (real results only)

- Owner, Windows (Stage 01, 12 Nov 2026): 85 passed. Nothing newer has been run by the owner.
- Builder, Linux sandbox, Python 3.13, pinned requirements, on the owner's Stage 06 repo (git HEAD f42a7e2) plus Stage 07: see the final reply for the exact counts of the last run (backend `pytest`, frontend `npm run check`, `npm run build`, `ruff check .`, `python scripts/check_docs.py`). Sandbox-only stubs: empty `data/raw`, `data/processed`.
- Stage 07 API check on a copy of the owner's real 500-ring `data/snapshots`: queue in live order, one dismissal moved the feedback offset by 0.1, audit chain verified. Drift and replay in that bundle are still `not_built` (exported before Stage 07).
- **NOT EXECUTED**: Stage 07 on real Stage 03 output (real drift and replay numbers unknown); live Groq or Gemini calls by the builder; Windows; CI on GitHub; a browser session against a live uvicorn recording decisions; the owner's own test run.

## Dataset citations and licence status

IBM AML (Altman et al., NeurIPS 2023 Datasets and Benchmarks): authors, title and venue confirmed on the NeurIPS proceedings page; page numbers, URL form and BibTeX not verified. Licence: the paper's supplement says "Community Data License Agreement"; the exact variant and its terms are NOT verified. Elliptic is not used yet (licence unchecked).

## Known bugs, caveats, open questions

- Feedback rule is unvalidated; do not present it as improving accuracy until tested against labels (Stage 08 candidate).
- PSI on real scores may be dominated by few events per window; windows under 500 events report "insufficient".
- Replay latency is retrospective and only counted when truth attribution is clear.
- One shared analyst token; names are free text; audit is tamper-evident, not tamper-proof; SQLite only until Stage 09.
- Real drift and replay on the real bundle: unknown (re-run `python scripts\export_snapshots.py` with Stage 03 outputs present). The real bundle's base threshold is about 0.0095 and expected values reach INR 2e10, so check the cost assumptions before presenting them. FX rates are placeholders. Elliptic licence unchecked.
- The Stage 03 findings (including a negative one) still need to be written into `docs/EVALUATION.md` after the real run.
- Stage 05 items remain: metrics key names unobserved, no neighbour nodes in case graphs, offline snapshot size on real data.
- CI never observed on GitHub. Timestamps run to 18 Sep although the data is described as 10 days.

## Stage 08 status (real results only)

- Builder, Linux sandbox, Python 3.13: backend `pytest` 665 passed, 8 skipped (5 are GraphSAGE tests that need torch); in a separate venv with torch 2.15.0 the 7 GraphSAGE tests passed; `ruff check .` clean; `python scripts/check_docs.py` OK; `scripts/secrets_scan.py` found nothing in the working tree or 39 commits; `pip-audit` on the installed environment clean after the pyarrow bump; `npm audit --omit=dev` 0, all deps 8 moderate (dev-only, eslint-config-next chain).
- **NOT EXECUTED**: any run on the real Elliptic files (no real Elliptic number exists); Windows; CI on GitHub (including the new audit workflow); frontend `npm run check` and `npm run build` (no frontend file changed); torch wheel on Windows.
- Open: Elliptic licence and column facts unverified; evaluation-pack items from the Stage 07 plan (feedback-rule experiment, robustness tables) moved to Stage 09 or later; no Elliptic page in the UI.

## Pending from the owner

1. Apply the Stage 07 zip over your repo, `pip install -r requirements.txt`, then `pytest`, `ruff check .`, `python scripts\check_docs.py`, and in `frontend`: `npm ci`, `npm run check`, `npm run build`. Paste the outputs.
2. After Stage 03 outputs exist: `python scripts\export_snapshots.py` and send the printed drift and replay status.
3. Send the Stage 06 Groq run report (verified share, fallbacks) when convenient.
4. Git (Git Bash): branch `stage-07-hitl-drift-replay`, merge, tag v0.8.0. Confirm earlier tags.
5. Confirm the buildathon deadline and FX rates.

## Next: Stage 09 (plan M9: deploy, docs, diagrams, demo)

Stage 09 candidates: deployment (Render or Fly, Vercel, Postgres) with `RS_TRUSTED_PROXY_HOPS` and `RS_API_DOCS=0`; the diagram specs document (to be created); full README pass; the evaluation pack deferred from Stage 08; an Elliptic page in the UI if wanted. The old Stage 08 text below is kept for reference.

### Old text (Stage 08 plan, superseded)

Stage 08: finish the evaluation pack. Ablations and robustness tables in `docs/EVALUATION.md`, a validation experiment for the feedback rule (simulate analyst labels from truth on the validation period, report effect on ring precision and review cost), the documented negative finding, and `scripts/reproduce.py` extended to cover drift and replay numbers. Files to touch: `scripts/reproduce.py`, `docs/EVALUATION.md`, `backend/ringsentinel/review/feedback.py` (only if the experiment motivates it), new Stage 08 tests. Stage 09: deployment (free-tier host, Postgres decision), the diagram specs document, final README, demo script. Do not start until the owner says "begin Stage 08".

## Continue-from-here prompt (paste into a new chat, with the project zip and this file attached)

```
You are my pair-programmer on RingSentinel (Razorpay AI Buildathon, Track 02, defense-only). First read HANDOVER.md, docs/PROJECT_EXPLAINER.md, docs/STAGE_08.md and docs/EVALUATION.md from the attached project zip, then follow the stage rules in the project instructions (prerequisites first, incremental zip with CHANGES_STAGE_NN.md containing only added or modified files, exact cmd commands, tests marked PASSED only if actually run else NOT EXECUTED, docs and explainer updated, git workflow, caveats at the end).
State: Stages 00 to 08 are built; I will paste test outputs and the real Stage 03 results. Wait for me to say "begin Stage 09", unless I paste results first, in which case help me interpret them.
Environment: Windows, cmd for everything except git (Git Bash), Python 3.13.3, dataset HI-Small. Your sandbox cannot reach Kaggle. Incremental zips do not contain earlier stages' sources: ask me for any file you need rather than guessing signatures.
```
