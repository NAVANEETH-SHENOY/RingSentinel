# RingSentinel

A defense-only abuse-ring detection and analyst-review tool, built solo for the Razorpay AI Buildathon, Track 02 (AI Risk Manager).

> **Status: Stage 02 built (noise layer, transfer graph with hub control, features); Stage 01 confirmed on the real data.** The graph-feature detector, ring extraction, AI layer, API and UI do not exist yet. Sections marked "Planned" are filled in by the stage named next to them. Nothing in this README claims a result that has not been produced.

## Problem

Fraud and abuse often come from coordinated groups of accounts, not single bad transactions. Analysts need to see the group, understand why it was flagged, and decide what to do, without drowning in false alarms.

## Who it is for

Fraud and risk analysts reviewing flagged groups of accounts. A human always decides; the tool never blocks anything by itself.

## What it will do (plain language)

RingSentinel links accounts through the money they move, finds groups that behave like a coordinated ring, ranks them by expected value to review, and explains each one. Every claim in an explanation is checked against the underlying data. The project is judged on honest measurement: precision and recall on a time-based held-out test, plus the rupee cost of wrongly flagging real users.

Screenshots or a GIF: Planned (Stage 05 and Stage 09).

## Architecture summary

An offline, deterministic pipeline produces static JSON snapshots; a thin API and a Next.js UI sit on top. The language model only explains evidence and never changes a score or takes an action. Details: `docs/ARCHITECTURE.md`. The zero-context guide for any reader or model: `docs/PROJECT_EXPLAINER.md`.

## Core logic

Written up as the stages land. Items 1 to 4 are implemented (Stage 02); items 5 to 10 are planned.

**1. Entity graph.** Nodes are accounts, identified by the account string. Edges are aggregated transfers (count, total INR amount, first and last time); self-transfers are counted but not linked. The IBM data has no device, IP or VPA information, so a synthetic, label-blind noise layer invents those attributes (marked derived) to test hub robustness. They are never presented as real data and never used as features.

**2. Hub control.** A node connected to very many others is weak evidence of coordination. An edge whose larger endpoint has degree d gets the weight

```
w(d) = 1 / log2(1 + d)      kept only if d <= D_max
```

and nodes above the cap D_max are dropped. The same formula is applied to the degree of a shared derived attribute, and the strength between two accounts is s(a, b) = sum of w(v) over their shared attributes v. D_max is tuned on the validation window only (smallest cap keeping 99 percent of validation ring accounts; 20 on HI-Small). Measured effect on HI-Small: it trims the giant component of the transfer graph by about 6 to 8 points and removes the total collapse caused by shared derived attributes, but the giant component remains (`docs/STAGE_02.md`).

**3. Candidate communities.** Connected components of the controlled graph; components larger than a size cap (200) are split with Louvain (igraph multilevel, seeded), recursively up to three times, and anything still too large is flagged. Honest result: these communities do not recover rings on this data (median Jaccard 0.04), so they serve as context features and rings are extracted from the flagged subgraph after scoring (Stage 03).

**4. Features.** Per account: counts, amounts, in and out degree, fan and flow ratios, reciprocity, burstiness (share of amount in the busiest hour), hub exposure, triangles, directed 3-cycles, PageRank. Per community: size, density, mean and max weighted degree, PageRank mass, cycles, fan ratio, burstiness, amount concentration. Windows are cumulative and past-only.

Planned: scoring, ring-level match, cost model, AI layer with verifier, human in the loop with hash-chained audit, drift (Stages 03, 04, 06, 07).

## Data

Primary dataset: IBM synthetic AML transactions (Kaggle), variant HI-Small by default. Real columns, labelling method, the label gap, real-versus-derived fields, and licence and citation status are in `docs/DATA.md`. The licence is not yet verified, and the citation's page numbers and BibTeX are not yet verified.

## Evaluation

Stage 01 produces validation-split baseline numbers only (velocity rule, tabular XGBoost; see `docs/STAGE_01.md`). The held-out test split is untouched. Planned: Stage 03 (protocol, results table for all detectors on the temporal test split, cost model, ablations, robustness, honest limitations, at least one negative finding).

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

Environment variables (names only): `RS_DATASET_VARIANT`, `RS_DATA_DIR`, `RS_SEED`, `RS_TRAIN_FRAC`, `RS_VAL_FRAC`, `RS_HUB_CAP`, `RS_ATTR_CAP`, `RS_COMMUNITY_CAP`, `RS_LOUVAIN_RESOLUTION`. See `.env.example` for reserved future names.

Deployment steps: Planned (Stage 09).

## Project structure

See the repo map in `docs/PROJECT_EXPLAINER.md`.

## Defense-only statement and responsible use

RingSentinel is a detection and review tool. It contains no evasion tuning and no attack tooling. Any perturbation of data (for example edge dropout) exists only to test robustness of the detectors and is labelled as such. No real customer data is used. Nothing is blocked automatically.

## Reproducibility

Planned: one script (`scripts/reproduce.py` [planned]) will regenerate every reported number.
