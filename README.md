# RingSentinel

A defense-only abuse-ring detection and analyst-review tool, built solo for the Razorpay AI Buildathon, Track 02 (AI Risk Manager).

> **Status: v1.0.0 (Stage 09, milestone M9).** The pipeline, API, analyst interface, AI layer, drift and replay are built and have been run on the real IBM AML HI-Small data (seed 42); Elliptic has been run too. The deployment files, a deployed-site smoke test and a demo script are included. **Not done, and said plainly:** the three hosts (Vercel, Render, Neon) have not been created by this tool, so the live URLs are yours to add below; the evaluation is not yet marked frozen in the bundle; the AI layer ran against a real model for 1 of 500 cases (see Limitations); the dataset licence terms have not been confirmed by you. Live demo URL: **to be added after you deploy** (`docs/DEPLOYMENT.md`).

## Problem

Fraud and abuse often come from coordinated groups of accounts, not single bad transactions. Analysts need to see the group, understand why it was flagged, and decide what to do, without drowning in false alarms.

## Who it is for

Fraud and risk analysts reviewing flagged groups of accounts. A human always decides; the tool never blocks anything by itself.

## What it does (plain language)

RingSentinel links accounts through the money they move, finds groups that behave like a coordinated ring, ranks them by expected value to review, and explains each one. Every claim in an explanation is checked against the underlying data. An analyst confirms, dismisses or holds each ring; every decision goes into a tamper-evident log. The project is judged on honest measurement: precision and recall on a time-based held-out test, plus the rupee cost of wrongly flagging real users.

Screenshots of the **real HI-Small bundle** (synthetic data, see Data; taken from the unfrozen bundle `af65200a`, so they show the "Numbers not frozen" banner): `docs/screenshots/real-queue.png`, `docs/screenshots/real-metrics.png`, `docs/screenshots/real-drift.png`, `docs/screenshots/real-replay.png`, `docs/screenshots/real-audit.png`. Older screenshots of the invented demo bundle (not results) are in the same folder. A recorded GIF or video: not included; `docs/DEMO_SCRIPT.md` is the voice-over script and recording checklist.

## Architecture summary

An offline, deterministic pipeline produces static JSON snapshots; a thin API and a Next.js UI sit on top. The language model only explains evidence and never changes a score or takes an action. Details: `docs/ARCHITECTURE.md`; diagrams you can regenerate: `docs/DIAGRAM_SPECS.md`; deployment: `docs/DEPLOYMENT.md`. The zero-context guide for any reader or model: `docs/PROJECT_EXPLAINER.md`.

```
IBM AML CSV + checksums (D1) -> events (D2) -> noise layer (D3) + time split (D4) -> graph and hub report (D5)
   -> features (D6) -> detector scores (D7) -> rings (D8) -> metrics (D9)
   -> AI case files (D10) + drift and replay (D11) -> snapshot bundle (D12, six JSON files, hash-checked)
   -> FastAPI (C11) + hash-chained audit log (D13, C12) -> Next.js UI (C15)
      static snapshots keep the UI working when the API sleeps
```

## Core logic

All ten items are implemented and have been run on the real HI-Small data. Items 8 (AI layer) and 9 (feedback) have a caveat each, stated in the item.

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

**8. AI layer with verifier (Stage 06; in the shipped bundle 1 case came from a real model, 99 from an offline stand-in, 400 from the template).** For each ring a language model writes a case file and a devil's advocate pass, using four read-only graph tools and a hard call budget. It sees accounts only as `acct-N` aliases. Every count and rupee amount it cites is a typed claim recomputed from the ring's own transfers:

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

**10. Drift (Stage 07; run on the real test period).** Each equal-width time window of the test period is compared with the validation scores using the population stability index over reference-quantile bins:

```
PSI = sum over bins of (test share - reference share) x ln(test share / reference share)      (shares floored at 1e-4)
```

On the real HI-Small test period the largest PSI is 0.064 (stable), but 6 of the 8 equal-width windows hold too few events to be scored, because most transfers fall in the first two windows. A window is ok below 0.10, warn from 0.10 and alert from 0.25 (a rule of thumb, set in `RS_PSI_WARN_LEVEL` and `RS_PSI_ALERT_LEVEL`, not a statistical test); windows with fewer than 500 events get no value. The plan compares with the training distribution; training scores were not kept (and would be in-sample), so the reference is the validation split. A retrospective **replay** steps through the test period and shows when each flagged ring became detectable and, where one true ring dominates it, the latency against the truth (a lower bound, since the scores use whole-window features).

The analyst interface (Stage 05, `docs/STAGE_05.md`) shows this queue and each ring's transfer graph (drawn from at most 500 accounts, chosen deterministically by transfer volume) and works from the snapshot files when the backend is off. With the backend on and an analyst token, the case page records confirm, dismiss and hold decisions (Stage 07).


## Data

Real fields and derived fields are listed separately in `docs/DATA.md`. In short: the transaction columns, the `Is Laundering` label, the Elliptic features and edges are **real as published** (the IBM data is itself synthetic); `amount_inr` (placeholder FX rates), `ring_id` (from the patterns file), the device, IP and VPA noise layer, all graph features and every score are **derived**.

**IBM AML (primary), variant HI-Small.** Altman, E., Blanuša, J., von Niederhäusern, L., Egressy, B., Anghel, A., Atasu, K. (2023). *Realistic Synthetic Financial Transactions for Anti-Money Laundering Models.* NeurIPS 2023, Datasets and Benchmarks Track. https://proceedings.neurips.cc/paper_files/paper/2023/hash/5f38404edff6f3f642d6fa5892479c42-Abstract.html (authors, title, venue and URL confirmed; **page numbers and BibTeX not verified**: copy the required form from the Kaggle page). Source: Kaggle, "IBM Transactions for Anti Money Laundering (AML)", https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml . **Licence:** IBM's repository states the data is released under CDLA-Sharing-1.0 (https://github.com/IBM/AML-Data); the paper's supplement says "a Community Data License Agreement". **You must confirm the licence line on the Kaggle page.** If CDLA-Sharing-1.0 applies, publishing data derived from it (this repository commits a bundle of rings with account ids and amounts) may need to be shared under the same terms: check this before making the repository public. This is not legal advice.

**Elliptic (second dataset, transaction level).** Weber, M., Domeniconi, G., Chen, J., Weidele, D. K. I., Bellei, C., Robinson, T., and Leiserson, C. E. (2019). *Anti-Money Laundering in Bitcoin: Experimenting with Graph Convolutional Networks for Financial Forensics.* KDD '19 Workshop on Anomaly Detection in Finance. arXiv:1908.02591, https://arxiv.org/abs/1908.02591 . Kaggle also asks for attribution to Elliptic (https://www.elliptic.co) and to that paper. Source: https://www.kaggle.com/datasets/ellipticco/elliptic-data-set . **Licence: CC BY-NC-ND 4.0** (as shown on the Kaggle page; https://creativecommons.org/licenses/by-nc-nd/4.0/): non-commercial, no derivatives. The raw files and any Elliptic-derived tables are not committed or served by the deployed site; only the results table (`docs/RESULTS_TABLE.md`) is. Keep it that way.

## Evaluation

**Protocol** (full text: `docs/EVALUATION.md`). Time-ordered split: train 3,046,861, validation 1,015,602, test 1,015,882 transfers (positives 2,297, 1,082, 1,798; the positive rate rises over time, so test is not the same distribution as train). Graph features come from past-only cumulative windows. Fitting uses train only; early stopping and every threshold use validation only; the test split is scored once per detector, enforced in code (`SplitVault`). Ring match is Jaccard >= 0.5, one-to-one, on the 370 known pattern rings only. A random ranking scores about the prevalence, 0.177 percent PR-AUC on test. Rupee amounts use placeholder FX rates and planning-assumption costs, so net-value figures are **not forecasts**.

The tables below are copied by `scripts/sync_readme_results.py` from the files that `scripts/reproduce.py` and `scripts/run_stage08.py table` write; edit nothing between the markers by hand (a test fails if they drift).

<!-- RESULTS:BEGIN -->

_Generated: do not edit by hand. Source: `docs/EVALUATION_RESULTS.md` (from `scripts/reproduce.py`) and `docs/RESULTS_TABLE.md` (from `scripts/run_stage08.py table`). Regenerate with `python scripts\sync_readme_results.py`._

Variant: HI-Small; seed 42; hub cap 20; ring match tau 0.5; ring minimum size 3.
Rupee assumptions (planning values, not measurements): review INR 250, false-positive account INR 500, loss capture rate 1. Amounts use placeholder FX rates.

**All detectors on the temporal test split**

Test split: 1,015,882 transfers, 1,798 positives (prevalence 0.00177).
Thresholds were chosen on validation only. Ring metrics: pattern rings only, Jaccard tau 0.5.

| Detector | Val PR-AUC | Test PR-AUC | Test P | Test R | Test F1 | Rings P | Rings R | Net value (INR) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| velocity | 0.0010 | 0.0014 | 0.0016 | 0.0211 | 0.0030 | 0.0000 | 0.0000 | 337,204,916 |
| xgb_tabular | 0.1185 | 0.2040 | 0.3203 | 0.3226 | 0.3214 | 0.1844 | 0.3474 | 48,335,410,389 |
| xgb_graph | 0.4534 | 0.6145 | 0.6999 | 0.5473 | 0.6142 | 0.2647 | 0.3789 | 48,650,197,812 |
| iforest | 0.0092 | 0.0052 | 0.0318 | 0.0289 | 0.0303 | 0.0417 | 0.0105 | 12,853,013,719 |

Test P, R, F1: transaction level at the validation F1 threshold. Rings P and R: ring level at that threshold. Net value: at the validation net-value threshold with the stated rupee assumptions. Validation PR-AUC is optimistic.

**Detection latency**

| Detector | Pattern rings with a flagged transfer | Median events | P90 events |
| --- | --- | --- | --- |
| velocity | 0 of 95 | n/a | n/a |
| xgb_tabular | 65 of 95 | 69193 | 514559 |
| xgb_graph | 87 of 95 | 0 | 192428 |
| iforest | 8 of 95 | 0 | 326705 |

**Ablation**

| Variant | Val PR-AUC | Test PR-AUC | Test F1 | Ring P | Ring R | Median ring size | Net value (INR) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| graph features OFF (tabular only) | 0.1185 | 0.2040 | 0.3214 | 0.1844 | 0.3474 | 4 | 48,335,410,389 |
| graph features ON, hub control OFF | 0.4784 | 0.6236 | 0.6169 | 0.2482 | 0.3579 | 5 | 48,728,680,348 |
| graph features ON, hub control ON | 0.4534 | 0.6145 | 0.6142 | 0.2647 | 0.3789 | 5 | 48,650,197,812 |

**Robustness: random removal of transfers from the test-window graph**

Testing only; not an evasion tool.

| Dropout | Test PR-AUC | Relative to no dropout | F1 at val threshold | Ring R |
| --- | --- | --- | --- | --- |
| 0% | 0.6145 | 1.000 | 0.6142 | 0.3789 |
| 10% | 0.5803 | 0.944 | 0.5847 | 0.3579 |
| 20% | 0.5188 | 0.844 | 0.5252 | 0.3368 |
| 30% | 0.4434 | 0.722 | 0.4439 | 0.3474 |
| 50% | 0.2690 | 0.438 | 0.2646 | 0.2632 |

**Two datasets, by detector role**

| Detector role | IBM AML test PR-AUC | IBM AML test F1 | Elliptic test PR-AUC | Elliptic test F1 |
| --- | --- | --- | --- | --- |
| Velocity rule | 0.001 | 0.003 | n/a (no clock time) | n/a |
| Unsupervised (Isolation Forest) | 0.005 | 0.030 | 0.036 | 0.122 |
| Tabular XGBoost | 0.204 | 0.321 | 0.768 | 0.737 |
| Graph-feature XGBoost (RingSentinel) | 0.614 | 0.614 | 0.772 | 0.752 |

Ring-level precision and recall and the rupee net value exist for IBM AML only.

<!-- RESULTS:END -->

**What the numbers support.**

- Graph features help a lot at transaction level on this data: test PR-AUC 0.6145 for the graph-feature XGBoost against 0.2040 for the same model without graph features, 0.0052 for an Isolation Forest and 0.0014 for the 24-hour velocity rule (which is at or below chance).
- The velocity rule and the Isolation Forest are weak baselines on this synthetic data. Beating them is not strong evidence; the comparison that matters is graph versus tabular XGBoost, which differ only in the graph columns.
- On Elliptic (a different task: transaction level, 49 time steps, no rings, no amounts) the graph-feature model scores 0.772 PR-AUC against 0.768 for the local-feature XGBoost. No confidence interval was computed, so this gap should be read as no measurable difference.

**Documented negative and weak findings.**

1. **Hub control did not improve transaction-level accuracy.** Removing it gives a slightly higher test PR-AUC (0.6236 against 0.6145); it improves ring precision and recall a little (0.2647 and 0.3789 against 0.2482 and 0.3579). The cap does trim the giant component of the transfer graph by 6 to 8 points (`docs/STAGE_02.md`) and removes the collapse caused by shared derived attributes, which is why it stays, but it is not a measured accuracy gain.
2. **Whole-graph communities do not recover rings** (median Jaccard 0.04), so rings are extracted from flagged transfers after scoring.
3. **Ring-level scores are modest:** at the validation threshold the graph model has ring precision 0.2647 and ring recall 0.3789. Strict ring precision is pessimistic because laundering outside the 370 known pattern rings (38 percent of positives) counts as a false ring.
4. **Net value at full loss capture is degenerate.** With capture = 1.0 the review threshold falls to 0.010 and every detector except velocity and the Isolation Forest earns almost the same net value (tabular 48.34 billion against graph 48.65 billion INR), driven by a few rings with enormous placeholder-FX amounts. Net value therefore cannot rank those detectors; PR-AUC and ring recall can. At capture 0.01 the numbers are far smaller and move with the cost settings (cost sensitivity table in `docs/EVALUATION_RESULTS.md`).
5. **Robustness falls with missing data:** removing 30 percent of test-window transfers leaves 72 percent of the PR-AUC, and 50 percent leaves 44 percent.
6. **Drift is mostly unscored here:** 6 of 8 test windows have too few events. The one score we have (largest PSI 0.064) says stable.
7. **Detection latency is a lower bound** because features use the whole test window; do not read "median 0 events" as real-time detection.

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

Stage 09 (deployment and release). Postgres audit log: put `RS_AUDIT_DB_URL=postgresql://...` in `.env` (names only here; the URL holds a password). The API creates its table on first use. Run the API from the slim set instead of the full one with `pip install -r requirements-api.txt`. After deploying, check the live site: `python scripts\smoke_deployed.py --api https://<api> --web https://<site> --expect-postgres --expect-docs-off --wait 120`. To test the Postgres store locally, create an empty database whose name contains `test` and set `RS_TEST_POSTGRES_URL` before `pytest` (those tests skip otherwise, and the fixture drops the `audit` table). Keep the README tables in step with a run: `python scripts\sync_readme_results.py` (or `--check`). Hosting steps: `docs/DEPLOYMENT.md`. Demo: `docs/DEMO_SCRIPT.md`.

Environment variables (names only): `RS_DATASET_VARIANT`, `RS_DATA_DIR`, `RS_SEED`, `RS_TRAIN_FRAC`, `RS_VAL_FRAC`, `RS_HUB_CAP`, `RS_ATTR_CAP`, `RS_COMMUNITY_CAP`, `RS_LOUVAIN_RESOLUTION`, `RS_NEG_SAMPLE_FRAC`, `RS_REVIEW_COST_INR`, `RS_FP_COST_INR`, `RS_LOSS_CAPTURE_RATE`, `RS_RING_TAU`, `RS_RING_MIN_SIZE`, `RS_GIT_COMMIT`, `RS_SNAPSHOT_DIR`, `RS_ANALYST_TOKEN`, `RS_AUDIT_DB_URL`, `RS_CORS_ORIGINS`, `RS_RATE_LIMIT_READ_PER_MIN`, `RS_RATE_LIMIT_WRITE_PER_MIN`, `RS_LLM_PROVIDER`, `RS_LLM_MODEL`, `RS_LLM_TIMEOUT_S`, `RS_LLM_MIN_INTERVAL_S`, `RS_LLM_MAX_TOOL_CALLS`, `RS_LLM_VERIFY_RETRIES`, `RS_AI_MAX_LLM_CASES`, `RS_FEEDBACK_STEP`, `RS_FEEDBACK_MAX_OFFSET`, `RS_FEEDBACK_CONFIRM_WEIGHT`, `RS_PSI_WARN_LEVEL`, `RS_PSI_ALERT_LEVEL`, `RS_DRIFT_WINDOWS`, `RS_DRIFT_BINS`, `RS_DRIFT_MIN_EVENTS`, `RS_REPLAY_STEPS`, `RS_RATE_LIMIT_AUTHFAIL_PER_MIN`, `RS_TRUSTED_PROXY_HOPS`, `RS_MAX_BODY_BYTES`, `RS_API_DOCS`, `RS_ELLIPTIC_DIR`, `RS_ELLIPTIC_TRAIN_LAST_STEP`, `RS_ELLIPTIC_VAL_LAST_STEP`, `RS_ELLIPTIC_HUB_CAP`, `RS_TEST_POSTGRES_URL` (tests only), `GROQ_API_KEY`, `GEMINI_API_KEY`. Frontend: `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_API_TIMEOUT_MS`. See `.env.example`.

Deployment steps (Vercel, Render, Neon, all free tier): `docs/DEPLOYMENT.md`; the Render Blueprint is `render.yaml`.

## Project structure

```
backend/ringsentinel/   pipeline: ingest, split, graph, features, detect, rings, evaluate, ai, snapshots, monitor, elliptic
backend/app/            API (C11), audit log (C12: audit.py SQLite, audit_pg.py Postgres), rate limits, config
backend/tests/          pytest suites by stage (test_stage09_* are the release checks)
frontend/               Next.js static export (C15); public/snapshots = optional local-only real bundle, public/demo-snapshots = committed invented fallback
scripts/                one command per stage, reproduce.py, export/sync snapshots, smoke_deployed.py, check_docs.py, secrets_scan.py
data/snapshots/         local-only frozen evaluation bundle (D12; ignored by Git); data/raw and data/processed stay local; data/audit is ignored
docs/                   ARCHITECTURE, DEPLOYMENT, DIAGRAM_SPECS, DEMO_SCRIPT, EVALUATION, DATA, STAGE_00..09, PROJECT_EXPLAINER
render.yaml, requirements-api.txt   API deployment    frontend/vercel.json   site headers
```

Full repo map with callers and callees: `docs/PROJECT_EXPLAINER.md`.

## Limitations (honest list)

- Synthetic data. IBM AML is generated; results show the method works on this benchmark, not on real traffic. No real customer data is used and no bank or Razorpay data was available.
- One run, one seed, no confidence intervals. Differences of a few thousandths are not evidence.
- Rupee amounts come from placeholder FX rates (`config/fx_rates_inr.json`), so queue amounts such as 48 billion INR for one ring are artefacts of the data and the placeholders, not claims about money. Cost assumptions are planning values.
- The queue's expected value uses an uncalibrated score. It orders rings; it does not forecast losses.
- AI layer: In the frozen 500-case evaluation bundle (retained locally and not included in the public release), 1 case came from a real language model, 99 from an offline stand-in (labelled as such in the interface), and 400 were rule-based templates. "Verified" means the cited counts and amounts match the graph, not that the interpretation is right. Its quality has not been evaluated on a model-written sample large enough to say anything.
- Analyst feedback (a bounded threshold shift) is a heuristic and has not been validated.
- The hash chain detects edits to earlier entries; it does not prevent them and cannot see entries removed from the end unless the head hash is recorded elsewhere. One shared analyst token, no individual accounts.
- Free-tier hosting sleeps; the first request after idle takes about a minute and the site falls back to saved snapshots meanwhile.
- Hosting steps and the Neon and Render behaviour are untested on the real services; the Postgres audit store was tested against a local Postgres 16 only.
- The replay timeline's triangle labels overlap when many rings become detectable in the same step (cosmetic).

## Defense-only statement and responsible use

RingSentinel is a detection and review tool. It contains no evasion tuning and no attack tooling. Any perturbation of data (for example edge dropout) exists only to test robustness of the detectors and is labelled as such. No real customer data is used. Nothing is blocked automatically.

## Reproducibility

`scripts/reproduce.py` regenerates every Stage 03 number with one command, reports whether the new `metrics.json` [generated] is identical to the previous run, writes `docs/EVALUATION_RESULTS.md` and then updates the README tables via `scripts/sync_readme_results.py`. Elliptic numbers: `python scripts\run_stage08.py run` then `table`. The bundle: `python scripts\export_snapshots.py` then `python scripts\sync_frontend_snapshots.py`. Same machine and inputs give identical numbers; XGBoost can differ slightly across platforms, so quote the platform (the committed numbers were produced on the owner's Windows machine).
