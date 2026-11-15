# RingSentinel

A defense-only abuse-ring detection and analyst-review tool, built solo for the Razorpay AI Buildathon, Track 02 (AI Risk Manager).

> **Status: Stage 07 built (decisions in the interface, bounded threshold feedback, live queue, drift with alerts, replay), on top of Stage 06 (AI layer with verifier), Stage 05 (analyst interface), Stage 04 (snapshot exporter and backend API with a hash-chained audit log) and Stage 03 (detectors, ring extraction, evaluation harness). Stages 03 to 07 are tested on synthetic, hand-made or invented demo data only; Stage 03 has not been run on the real data yet, so no real result exists, and no live language-model call has been made. Deployment, diagram specs and the final results are still to come.**

## Problem

Fraud and abuse often come from coordinated groups of accounts, not single bad transactions. Analysts need to see the group, understand why it was flagged, and decide what to do, without drowning in false alarms.

## Who it is for

Fraud and risk analysts reviewing flagged groups of accounts. A human always decides; the tool never blocks anything by itself.

## What it will do (plain language)

RingSentinel links accounts through the money they move, finds groups that behave like a coordinated ring, ranks them by expected value to review, and explains each one. Every claim in an explanation is checked against the underlying data. The project is judged on honest measurement: precision and recall on a time-based held-out test, plus the rupee cost of wrongly flagging real users.

Screenshots (of the built-in **demo data**, which is invented; not results): `docs/screenshots/queue.png`, `docs/screenshots/case-ring.png`, `docs/screenshots/case-capped-500.png`, `docs/screenshots/metrics-curves.png`, `docs/screenshots/audit.png`, `docs/screenshots/queue-backend-off.png`, `docs/screenshots/drift.png`, `docs/screenshots/replay.png`. A GIF and screenshots of real results: Planned (Stage 09).

## Architecture summary

An offline, deterministic pipeline produces static JSON snapshots; a thin API and a Next.js UI sit on top. The language model only explains evidence and never changes a score or takes an action. Details: `docs/ARCHITECTURE.md`. The zero-context guide for any reader or model: `docs/PROJECT_EXPLAINER.md`.

## Core logic

Written up as the stages land. Items 1 to 4 are implemented (Stage 02); items 5 to 7 are implemented (Stage 03, not yet run on the real data); item 9 is implemented (Stages 04 and 07); item 8 is implemented with a fake model only (Stage 06); item 10 is implemented (Stage 07, run on synthetic and demo data only).

**1. Entity graph.** Nodes are accounts, identified by the account string. Edges are aggregated transfers (count, total INR amount, first and last time); self-transfers are counted but not linked. The IBM data has no device, IP or VPA information, so a synthetic, label-blind noise layer invents those attributes (marked derived) to test hub robustness. They are never presented as real data and never used as features.

**2. Hub control.** A node connected to very many others is weak evidence of coordination. An edge whose larger endpoint has degree d gets the weight

```
w(d) = 1 / log2(1 + d)      kept only if d <= D_max
```

and nodes above the cap D_max are dropped. The same formula is applied to the degree of a shared derived attribute, and the strength between two accounts is s(a, b) = sum of w(v) over their shared attributes v. D_max is tuned on the validation window only (smallest cap keeping 99 percent of validation ring accounts; 20 on HI-Small). Measured effect on HI-Small: it trims the giant component of the transfer graph by about 6 to 8 points and removes the total collapse caused by shared derived attributes, but the giant component remains (`docs/STAGE_02.md`).

**3. Candidate communities.** Connected components of the controlled graph; components larger than a size cap (200) are split with Louvain (igraph multilevel, seeded), recursively up to three times, and anything still too large is flagged. Honest result: these communities do not recover rings on this data (median Jaccard 0.04), so they serve as context features and rings are extracted from the flagged subgraph after scoring (Stage 03).

**4. Features.** Per account: counts, amounts, in and out degree, fan and flow ratios, reciprocity, burstiness (share of amount in the busiest hour), hub exposure, triangles, directed 3-cycles, PageRank. Per community: size, density, mean and max weighted degree, PageRank mass, cycles, fan ratio, burstiness, amount concentration. Windows are cumulative and past-only.

**5. Scoring.** Each transfer gets a score from four detectors: a 24-hour velocity rule, a tabular XGBoost, a graph-feature XGBoost (the transfer's own columns plus the Stage 02 features of its sender and receiver) and an unsupervised Isolation Forest. Fitting uses train only; early stopping and every threshold use validation only; the test split is scored once per detector. Rings are then extracted from the flagged transfers (connected components, Louvain above the size cap), because whole-graph communities do not recover rings.

**6. Ring-level match.** A predicted ring is a true positive when

```
J(P, G) = |P and G| / |P or G|  >=  tau      (tau = 0.5; 0.3 and 0.7 also reported)
```

with a ground-truth pattern ring G, matched one-to-one. Ring recall covers pattern rings only (3,209 of the 5,177 positives); this is stated next to every ring number.

**7. Cost model.** The review threshold maximises net value in rupees:

```
NV = capture x (INR amount of illicit flagged transfers in caught rings)
     - c_review x (rings flagged) - c_fp x (legitimate accounts inside flagged rings)
```

with planning-assumption defaults of INR 250 per review and INR 500 per wrongly included account (justification and a sensitivity sweep in `docs/EVALUATION.md`).

**8. AI layer with verifier (built in Stage 06; live model calls not yet run).** For each ring a language model writes a case file and a devil's advocate pass, using four read-only graph tools and a hard call budget. It sees accounts only as `acct-N` aliases. Every count and rupee amount it cites is a typed claim recomputed from the ring's own transfers:

```
claim ok  <=>  metric recomputed from the ring's edges == claimed value
               (counts exactly; rupees within INR 1)
```

Prose is also scanned for unknown aliases, dates and numbers. Any failure falls back to a rule-based template case file built only from the data, and templates are excluded from the reported verified share. The model cannot change a score, rank or action; the bundle merge accepts only the `ai` field. "Verified" means the cited facts match the data, not that the interpretation is right. Questions to the queue become a validated JSON query (never code or SQL). See `docs/STAGE_06.md`.

**9. Human in the loop, with bounded feedback (Stages 04 and 07).** The review queue is ordered by an expected-value heuristic computed from the model score and the agreed rupee costs:

```
EV = score x capture x amount_inr - c_review - c_fp x n_members x (1 - score)
```

The score is not a calibrated probability, so this orders rings for review; it does not forecast rupees. An analyst confirms, dismisses or holds a ring through the API. Every action is appended to a log in which entry i stores the hash of entry i-1:

```
hash_i = SHA-256( canonical_json(seq, ts, ring, action, analyst, note, idempotency_key, request_digest, hash_{i-1}) )
```

so changing or deleting an earlier entry is detected when the chain is verified (it detects tampering; it does not prevent it, and cannot see entries cut off from the end unless the head hash is recorded elsewhere).

Analyst decisions also steer the queue, inside fixed bounds. The review threshold is shifted in log-odds by the net number of dismissals, and the open rings are re-ranked by the expected value of the shifted score:

```
offset = clamp(step x (dismissed - w x confirmed), 0, max_offset)           step 0.1, w 1, max 1.5 (hard ceilings 1, 5, 3)
effective threshold = sigmoid(logit(base threshold) + offset)
adjusted score      = sigmoid(logit(score) - offset)
```

The shift is recomputed from the audit log on every read; stored scores, ranks and detectors never change, confirmations only cancel dismissals, holds count for nothing, and the threshold can never fall below the validated one. **This rule is a heuristic and has not been validated**; the interface says so. Details: `docs/STAGE_07.md`.

**10. Drift (Stage 07; run on synthetic and demo data only).** Each equal-width time window of the test period is compared with the validation scores using the population stability index over reference-quantile bins:

```
PSI = sum over bins of (test share - reference share) x ln(test share / reference share)      (shares floored at 1e-4)
```

A window is ok below 0.10, warn from 0.10 and alert from 0.25 (a rule of thumb, set in `RS_PSI_WARN_LEVEL` and `RS_PSI_ALERT_LEVEL`, not a statistical test); windows with fewer than 500 events get no value. The plan compares with the training distribution; training scores were not kept (and would be in-sample), so the reference is the validation split. A retrospective **replay** steps through the test period and shows when each flagged ring became detectable and, where one true ring dominates it, the latency against the truth (a lower bound, since the scores use whole-window features).

The analyst interface (Stage 05, `docs/STAGE_05.md`) shows this queue and each ring's transfer graph (drawn from at most 500 accounts, chosen deterministically by transfer volume) and works from the snapshot files when the backend is off. With the backend on and an analyst token, the case page records confirm, dismiss and hold decisions (Stage 07).


## Data

Primary dataset: IBM synthetic AML transactions (Kaggle), variant HI-Small by default. Real columns, labelling method, the label gap, real-versus-derived fields, and licence and citation status are in `docs/DATA.md`. The licence is not yet verified, and the citation's page numbers and BibTeX are not yet verified.

A second dataset, the Elliptic Bitcoin transaction graph (Weber et al. 2019, arXiv:1908.02591), is supported at transaction level in Stage 08; its licence is not verified and no real Elliptic result exists yet. Real versus derived fields: `docs/DATA.md`.

## Evaluation

The protocol, detectors, cost model, ablations, robustness test and latency definition are in `docs/EVALUATION.md`. The results table for all detectors on the temporal test split will come from `scripts/reproduce.py` into `docs/EVALUATION_RESULTS.md` [generated]; **no Stage 03 result exists yet**, so none is shown here. Stage 01 validation-split baselines are in `docs/STAGE_01.md`. Negative findings already documented: the velocity rule is at chance on validation; Louvain communities do not recover rings; hub control only trims the giant component of the real transfer graph by 6 to 8 points.

## Setup, run and test (Windows, cmd)

Run from the repository root.

```
py -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
pytest
ruff check .
python scripts\check_docs.py
```

Stage 01 (after placing the two HI-Small files in `data\raw`): `python scripts\run_stage01.py`.

Stage 02 (after Stage 01): `python scripts\run_stage02.py`, then `python scripts\ablation_giant_component.py`.

Stage 03 (after Stage 02): `python scripts\run_stage03.py`, or `python scripts\reproduce.py` to run everything and write the results document.

Stage 04 (after Stage 03): `python scripts\export_snapshots.py` writes the snapshot bundle; `python scripts\run_api.py` serves it at http://127.0.0.1:8000 (interactive docs at /api/docs). Put a token of at least 16 characters in `.env` as `RS_ANALYST_TOKEN` to allow analyst actions. Endpoints, status codes and the audit log design: `docs/STAGE_04.md`.

Stage 05 (from `frontend`; Node 22 LTS or newer): `npm ci`, then `npm run dev` and open http://localhost:3000 (demo data until a real bundle is synced). `npm run check` runs the type check, lint and tests; `npm run build` writes the static site to `frontend/out`. With the API running, put `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000` in `frontend/.env.local` [generated]. To show real results: `python scripts\export_snapshots.py`, then `python scripts\sync_frontend_snapshots.py`.

Stage 07 (after Stage 03, with the API running as above): `python scripts\export_snapshots.py` now also builds `drift.json` [generated] and `replay.json` [generated] when the scores and events tables exist (`--no-monitor` skips them); `python scripts\make_demo_bundle.py` rebuilds the demo bundle with drift, replay and template case files from invented data. In the interface (set `NEXT_PUBLIC_API_BASE_URL`, start the API with `RS_ANALYST_TOKEN` set) open a case, enter your name and the token, and confirm, dismiss or hold; the queue then shows the live order and the feedback card. See `docs/STAGE_07.md`.

Stage 08 (Elliptic; put the three Kaggle CSV files in `data\raw\elliptic`): `python scripts\run_stage08.py verify`, then `run`, then `table`; `demo` runs on synthetic files. Optional GraphSAGE: `pip install -r requirements-gnn.txt` and `run --gnn`. Secrets check: `python scripts\secrets_scan.py`. See `docs/STAGE_08.md`.

Stage 06 (after Stage 04): `python scripts\run_stage06.py --provider fake` runs the whole AI layer offline; for a live run put `GROQ_API_KEY` in `.env`, then `python scripts\run_stage06.py --provider groq --limit 20`. Ask the queue a question: `python scripts\ai_query.py "rings with a cycle"`. See `docs/STAGE_06.md`.

Environment variables (names only): `RS_DATASET_VARIANT`, `RS_DATA_DIR`, `RS_SEED`, `RS_TRAIN_FRAC`, `RS_VAL_FRAC`, `RS_HUB_CAP`, `RS_ATTR_CAP`, `RS_COMMUNITY_CAP`, `RS_LOUVAIN_RESOLUTION`, `RS_NEG_SAMPLE_FRAC`, `RS_REVIEW_COST_INR`, `RS_FP_COST_INR`, `RS_LOSS_CAPTURE_RATE`, `RS_RING_TAU`, `RS_RING_MIN_SIZE`, `RS_GIT_COMMIT`, `RS_SNAPSHOT_DIR`, `RS_ANALYST_TOKEN`, `RS_AUDIT_DB_URL`, `RS_CORS_ORIGINS`, `RS_RATE_LIMIT_READ_PER_MIN`, `RS_RATE_LIMIT_WRITE_PER_MIN`, `RS_LLM_PROVIDER`, `RS_LLM_MODEL`, `RS_LLM_TIMEOUT_S`, `RS_LLM_MIN_INTERVAL_S`, `RS_LLM_MAX_TOOL_CALLS`, `RS_LLM_VERIFY_RETRIES`, `RS_AI_MAX_LLM_CASES`, `RS_FEEDBACK_STEP`, `RS_FEEDBACK_MAX_OFFSET`, `RS_FEEDBACK_CONFIRM_WEIGHT`, `RS_PSI_WARN_LEVEL`, `RS_PSI_ALERT_LEVEL`, `RS_DRIFT_WINDOWS`, `RS_DRIFT_BINS`, `RS_DRIFT_MIN_EVENTS`, `RS_REPLAY_STEPS`, `RS_RATE_LIMIT_AUTHFAIL_PER_MIN`, `RS_TRUSTED_PROXY_HOPS`, `RS_MAX_BODY_BYTES`, `RS_API_DOCS`, `RS_ELLIPTIC_DIR`, `RS_ELLIPTIC_TRAIN_LAST_STEP`, `RS_ELLIPTIC_VAL_LAST_STEP`, `RS_ELLIPTIC_HUB_CAP`, `GROQ_API_KEY`, `GEMINI_API_KEY`. See `.env.example` for reserved future names.

Deployment steps: Planned (Stage 09).

## Project structure

See the repo map in `docs/PROJECT_EXPLAINER.md`.

## Defense-only statement and responsible use

RingSentinel is a detection and review tool. It contains no evasion tuning and no attack tooling. Any perturbation of data (for example edge dropout) exists only to test robustness of the detectors and is labelled as such. No real customer data is used. Nothing is blocked automatically.

## Reproducibility

`scripts/reproduce.py` regenerates every Stage 03 number with one command and reports whether the new `metrics.json` [generated] is identical to the previous run. It has been tested on synthetic data only; the real-data run is pending.
