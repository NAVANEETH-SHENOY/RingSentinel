# RingSentinel v1.0.0

A defense-only abuse-ring detection and analyst-review tool for the Razorpay AI Buildathon, Track 02 (AI Risk Manager). Solo project. Not affiliated with or endorsed by Razorpay.

## What is in it

- Offline pipeline: IBM AML HI-Small (and Elliptic) to an account graph with hub control, four detectors, candidate rings, an evaluation with a rupee cost model, ablations, robustness, drift and a retrospective replay.
- Snapshot bundle (six hash-checked JSON files), a FastAPI backend with a hash-chained audit log (SQLite locally, Postgres when deployed), and a static Next.js interface that works read-only from saved snapshots when the API sleeps.
- AI layer: explanations whose cited facts are recomputed from the ring's own transfers; template fallback; the model never changes a score or an action.
- Release material: deployment files and guide, a deployed-site smoke test, diagram specs, a demo script, generated README results tables.

## Headline results (HI-Small test split, seed 42, one run)

Transaction-level PR-AUC: velocity rule 0.0014, Isolation Forest 0.0052, tabular XGBoost 0.2040, graph-feature XGBoost 0.6145 (random ranking 0.0018). Ring level for the graph model: precision 0.2647, recall 0.3789 (Jaccard 0.5, known pattern rings only). Elliptic: 0.772 (graph) against 0.768 (local features).

## Negative and weak findings

Hub control did not raise PR-AUC (0.6145 with, 0.6236 without). Whole-graph communities do not recover rings. Net value at full loss capture is degenerate. Most test windows have too few events for drift to be scored. Ring precision is modest. Robustness falls to 72 percent of PR-AUC at 30 percent edge removal.

## Known limitations

Synthetic data; one seed and no confidence intervals; placeholder FX rates make rupee figures meaningless as money; 1 of 500 case files is from a real model; the analyst-feedback rule is unvalidated; one shared analyst token; hosting steps untested on the real services; evaluation not yet marked frozen.

## Data and licences

IBM AML: Altman et al. 2023, NeurIPS Datasets and Benchmarks; licence reported as CDLA-Sharing-1.0, to be confirmed on the Kaggle page. Elliptic: Weber et al. 2019; CC BY-NC-ND 4.0. Full citations: README and `docs/DATA.md`.

## Responsible use

Defense-only. No evasion tuning or attack tooling; edge dropout exists only to test robustness. No real customer data. Nothing is blocked automatically; a human decides.
