# Demo script: voice-over, flow and file map

Target length about 7 minutes (about 1,000 spoken words at a relaxed pace). A 3-minute cut is marked at the end. Everything below uses the real HI-Small results from the committed bundle (`af65200a`, seed 42). The data is synthetic and the rupee amounts come from placeholder exchange rates, so the script never reads a rupee figure aloud.

## 0. Before you record (10 minutes)

| Step | Command or action (Windows cmd, repo root unless stated) |
| --- | --- |
| Freeze the numbers, if you have not | `python scripts\export_snapshots.py --frozen --git-commit <short sha>`, then `python scripts\sync_frontend_snapshots.py`. This removes the "Numbers not frozen" banner. The screenshots in the README still show it until you retake them |
| Local demo (no hosting needed) | Terminal 1: `python scripts\run_api.py`. Terminal 2, from `frontend`: `npm run dev`. Open http://localhost:3000 |
| Hosted demo | Open `https://<api>.onrender.com/api/v1/live` once, wait for `{"status":"ok"}`, then open the Vercel site. The first request after idle takes about a minute |
| Token | Set `RS_ANALYST_TOKEN` before starting the API. Type it into the page during the take; never show `.env`, the Render dashboard or the Neon connection string. Do not tick "Remember the token" |
| Browser | One window, 1440 by 900, zoom 100 to 110 percent, bookmarks bar hidden, a clean profile |
| Dry run | `python scripts\smoke_deployed.py --api <api> --web <site> --wait 120`. No FAIL lines |
| Two tabs ready | Queue, and the two cases used below: `R-3b44acbc4a0e` (rank 2, explanation written by a real model) and `R-13dc384ba17a` (rank 10, 16 accounts, a good graph) |
| Do not use | the `--write-check` option on the public API right before recording: it adds one permanent entry to the audit log |

## 1. Flow at a glance

| # | Time | You show | What it proves | Where it lives |
| --- | --- | --- | --- | --- |
| 1 | 0:00 | Title and the review queue | The problem and the product | `frontend/src/components/QueueView.tsx` |
| 2 | 0:30 | Architecture diagram | Offline pipeline, thin API, static fallback, LLM that only explains | `docs/DIAGRAM_SPECS.md` (diagram 1), `docs/ARCHITECTURE.md` |
| 3 | 1:30 | Data flow diagram | Real data, time-ordered split, no leakage | `docs/DIAGRAM_SPECS.md` (diagram 2), `docs/DATA.md` |
| 4 | 2:30 | Review queue | A ranked list of groups, not single transactions | `/` page, `data/snapshots/queue.json` |
| 5 | 3:15 | Case `R-13dc384ba17a`, then `R-3b44acbc4a0e` | Graph view, why-flagged signals, verified explanation | `frontend/src/components/CaseView.tsx`, `backend/ringsentinel/ai/verifier.py` |
| 6 | 4:15 | Record a decision, then the Audit page | Human gate, idempotency, tamper-evident chain | `frontend/src/components/ActionPanel.tsx`, `backend/app/audit.py`, `backend/app/audit_pg.py` |
| 7 | 5:00 | Metrics page | The edge: graph against tabular, velocity and isolation forest | `docs/EVALUATION_RESULTS.md`, `data/snapshots/metrics.json` |
| 8 | 5:50 | Drift, Replay, README limitations | Honest negatives and caveats | `docs/STAGE_07.md`, README "Limitations" |
| 9 | 6:30 | Comparison slide (table in section 3) | How it stands out, without overclaiming | this file |
| 10 | 7:00 | Close | Deploy story and what is next | `docs/DEPLOYMENT.md` |

## 2. Voice-over (read naturally; pauses are marked with a slash)

**1. Problem (queue on screen, 0:00)**
"Fraud and abuse rarely come from one bad transaction. They come from groups of accounts working together. An analyst who only sees single transfers is looking at the wrong unit. / This is RingSentinel, a defense-only tool for the Razorpay AI Buildathon, Risk Manager track. It finds groups of accounts that behave like a ring, ranks them by how worthwhile they are to review, explains each one, and leaves the decision to a person. Nothing is ever blocked automatically."

**2. Architecture (diagram 1, 0:30)**
"Here is how it is built. On the left is an offline pipeline that runs on my machine: it ingests the transactions, splits them by time, builds an account graph, computes features, scores every transfer, and groups the flagged ones into candidate rings. It also measures itself, and watches for drift. / All of that is packaged into one small bundle of JSON files, each one hash-checked. / On the right is the online part. A thin FastAPI service loads that bundle and records analyst decisions in a tamper-evident log. A static web app sits on top, and if the API is asleep, because this runs on free hosting, the web app falls back to the saved snapshots, so you still see everything read-only. / At the top is the language model. Its job is to explain evidence. It never changes a score, a rank or a decision, and every number it quotes is rechecked against the graph."

**3. Data flow (diagram 2, 1:30)**
"Now the data. The data is the IBM synthetic anti-money-laundering set, about five million transfers, with ground truth. It is synthetic, so I'm not claiming this is real traffic. / The first rule of the pipeline: split by time before building anything. Train, then validation, then test, in order. Graph features for each period use only past transfers. Models are fitted on train, every threshold is chosen on validation, and the test period is scored exactly once per detector, and the code enforces that, it raises if you try twice. / Then the graph: accounts are nodes, transfers are edges, and very busy accounts are down-weighted, because a hub that talks to everyone is weak evidence of coordination. Features go into four detectors, flagged transfers are grouped into rings, and everything lands in the bundle you see on the right."

**4. Queue (queue page, 2:30)**
"This is the analyst's view. Each row is a ring, a group of accounts, not a single transaction. They are ordered by an expected-value heuristic: the model's score, weighed against what a review costs and what a wrong flag costs. I want to be clear that the score is not a calibrated probability, so this orders the work, it doesn't forecast money. And ignore the rupee amounts: they come from placeholder exchange rates on synthetic data."

**5. Case view (3:15)**
(Open `R-13dc384ba17a`.) "Open a ring and you get the transfer graph. Sixteen accounts, thirty links. Arrow direction is sender to receiver, line width is value moved. And here's why it was flagged: the strongest signals from the model, in plain names. / Now the explanation." (Open `R-3b44acbc4a0e`.) "This one was written by a language model. The green badge says the facts were verified against the transfers: every account count and amount in the text was recomputed from this ring's own edges. If any check fails, the system throws the model's text away and shows a rule-based summary instead. / 'Verified' means the facts match the data. It does not mean the interpretation is right, and the page says so. In the shipped bundle, most case files are templates or an offline stand-in, and the page labels them that way. Only a small sample came from a real model, and I won't pretend that sample proves anything about explanation quality."

**6. Decision and audit (4:15)**
"Now the human part. I enter my name and the analyst token and choose confirm, dismiss or hold. / Every decision is appended to a log where each entry contains the hash of the one before it. If someone edits an earlier entry, verification fails. It detects tampering, it doesn't prevent it, and it can't see entries removed from the very end unless the latest hash is stored elsewhere. Submitting the same decision twice is safe: it replays, it doesn't duplicate. / In production this log lives in Postgres, because the free host's disk is erased on every restart. / Dismissals also nudge the review threshold up a little, within fixed bounds, and the queue re-ranks. That rule is a heuristic and the interface says it hasn't been validated."

**7. The edge (Metrics page, 5:00)**
"Here's the result I care about. On the held-out test period, a velocity rule, the classic 'too many transfers in a day' check, scores 0.0014 PR-AUC, which is no better than chance. An isolation forest scores 0.005. A tabular XGBoost on each transfer's own columns scores 0.204. The same XGBoost with graph features added, which is the only difference, scores 0.614. That is about three times the tabular model, from the graph alone. / At the ring level, the graph model finds 38 percent of the known rings at 26 percent precision, against 35 percent and 18 percent for the tabular one. That's a smaller gap, and 26 percent precision is modest, I'm not hiding that. Strict ring precision is also pessimistic here because about 38 percent of the laundering transfers belong to no known ring. / On Elliptic, a Bitcoin dataset, the graph features give 0.772 against 0.768, which is no measurable difference."

**8. Honest findings (Drift and Replay, 5:50)**
"A few things didn't go the way I hoped, and they're documented. Hub control did not improve accuracy: without it the transaction-level score is slightly higher. It does shrink the giant component, which is why I kept it, but it's not a measured win. The net-value number at full loss capture is degenerate: every strong detector earns almost the same, so I rely on PR-AUC and ring recall instead. The drift page marks most test windows as 'too few events' because the transfers are concentrated early; the one number it gives says stable. And robustness: remove thirty percent of transfers and the score falls to about seventy-two percent of itself. / One seed, one run, no confidence intervals, synthetic data. Treat the gaps accordingly."

**9. How it stands out (comparison slide, 6:30)**
"So where does it stand out? Not by claiming to beat commercial products. I haven't benchmarked against them. Compared with the approaches it replaces: a rule engine looks at one transaction and, here, does no better than chance. A per-transaction model misses the structure. A black-box graph model or an AI agent gives you a score or a story with nothing to check. / RingSentinel gives the analyst a group, a reason, an explanation whose facts are verified, a human decision that is logged tamper-evidently, and an evaluation where the negative results are published next to the positive ones."

**10. Close (7:00)**
"It's deployed on free tiers, a static site on Vercel, the API on Render, the log in Neon Postgres, with a smoke test that checks the live site, and a script that regenerates every number in the README. The code, the data citations and the limitations are all in the repository. Thank you."

## 3. Comparison slide (put this on screen in segment 9)

Only measured claims are in the "measured here" column. Nothing is claimed about any vendor's product.

| Approach | What an analyst gets | Measured here (HI-Small test PR-AUC) | Weakness this project addresses |
| --- | --- | --- | --- |
| Velocity or rule engine | One alert per transaction | 0.0014 (about chance) | Blind to coordination |
| Per-transaction ML (tabular XGBoost) | A score per transfer | 0.204 | Ignores who is connected to whom |
| Unsupervised anomaly (isolation forest) | An outlier flag | 0.0052 | No labels used; flags unusual, not abusive |
| Black-box graph model or AI agent (not benchmarked here) | A score or a narrative | not measured | Nothing to verify, hard to audit |
| **RingSentinel (graph features + rings + verifier)** | A ranked group, why it was flagged, verified facts, logged decision | **0.614** (ring recall 0.379, ring precision 0.265) | Modest ring precision; synthetic data; one seed |

The four "edge" points to land: (1) measured graph lift, same model with and without graph columns; (2) the unit of review is a ring; (3) explanations that cannot cite a fact the data does not contain; (4) auditable human-in-the-loop with honest, published negatives. A fifth, practical one: it keeps working read-only when the backend sleeps, and it runs on free tiers.

## 4. Where the files are

| Topic | Path |
| --- | --- |
| Architecture and decisions | `docs/ARCHITECTURE.md`, `docs/PROJECT_EXPLAINER.md` |
| Diagrams (Mermaid plus element tables) | `docs/DIAGRAM_SPECS.md` |
| Real data: columns, labels, citations, licences | `docs/DATA.md` |
| Evaluation protocol and every table | `docs/EVALUATION.md`, `docs/EVALUATION_RESULTS.md`, `docs/RESULTS_TABLE.md` |
| Pipeline code | `backend/ringsentinel/` (subfolders graph, detect and rings) |
| AI layer and verifier | `backend/ringsentinel/ai/`, `docs/STAGE_06.md` |
| API and audit log | `backend/app/`, `docs/STAGE_04.md` |
| Frontend | `frontend/src/components/`, `docs/STAGE_05.md` |
| Drift and replay | `backend/ringsentinel/monitor/`, `docs/STAGE_07.md` |
| The bundle the demo shows | `data/snapshots/`, `frontend/public/snapshots/` |
| Deployment and smoke test | `docs/DEPLOYMENT.md`, `render.yaml`, `scripts/smoke_deployed.py` |
| One-command reproduction | `scripts/reproduce.py`, `scripts/sync_readme_results.py` |
| Screenshots of the real bundle | `docs/screenshots/real-*.png` |

## 5. Do not say

- "Production-ready", "state of the art", "beats [any named product]", "detects X percent of real fraud".
- Any rupee figure as a loss or saving: amounts are placeholder-FX artefacts.
- "The AI explains every ring": 1 of 500 case files is from a real model; 99 are an offline stand-in; 400 are templates.
- "Hub control improves accuracy" or "drift detected nothing, so it is robust".
- "Validated" about the analyst-feedback rule.

## 6. Three-minute cut

Segments 1 (shortened), 2, 5 (one case only), 7 and 9. Drop 3, 4, 6, 8; keep one sentence from 8: "hub control did not improve accuracy, and every number is one seed on synthetic data."
