# RingSentinel

A defense-only abuse-ring detection and analyst-review tool, built solo for the Razorpay AI Buildathon, Track 02 (AI Risk Manager).

> **Status: Stage 00 (scaffold) complete.** No detection code exists yet. Sections marked "Planned" are filled in by the stage named next to them. Nothing in this README claims a result that has not been produced.

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

Planned (written up with formulas as the stages land):

- Entity graph and hub control with the IDF-style weight: Stage 02
- Candidate rings, features and scoring: Stages 02 and 03
- Ring-level match, cost model, drift: Stages 03 and 07
- AI layer with verifier: Stage 06
- Human in the loop with hash-chained audit: Stage 04 and Stage 07

## Data

Planned: Stage 01. Primary dataset: IBM synthetic AML transactions (Kaggle), variant HI-Small by default. Full citations, licence status, and the split between real and derived fields will be added only after they are checked on the source pages.

## Evaluation

Planned: Stage 03 (protocol, results table for all detectors on the temporal test split, cost model, ablations, robustness, honest limitations, at least one negative finding).

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

Environment variables (names only): `RS_DATASET_VARIANT`, `RS_DATA_DIR`, `RS_SEED`. See `.env.example` for reserved future names.

Deployment steps: Planned (Stage 09).

## Project structure

See the repo map in `docs/PROJECT_EXPLAINER.md`.

## Defense-only statement and responsible use

RingSentinel is a detection and review tool. It contains no evasion tuning and no attack tooling. Any perturbation of data (for example edge dropout) exists only to test robustness of the detectors and is labelled as such. No real customer data is used. Nothing is blocked automatically.

## Reproducibility

Planned: one script (`scripts/reproduce.py` [planned]) will regenerate every reported number.
