# Changelog

One entry per tag. Format: Keep a Changelog style, Conventional Commit prefixes.

## v0.4.0 - Stage 03: detectors, ring extraction, evaluation (pending owner confirmation)

### Added
- `backend/ringsentinel/detect/`: tabular features and trailing 24-hour counts, design matrices from the Stage 02 window features, XGBoost and Isolation Forest fitting, and `SplitVault` (the test split is released once per detector).
- `backend/ringsentinel/rings/extract.py`: ring extraction from flagged transfers.
- `backend/ringsentinel/evaluate/`: metrics, Jaccard ring match, rupee cost model, per-detector report, cost sweep, latency.
- `backend/ringsentinel/stage03.py`, `scripts/run_stage03.py`, `scripts/reproduce.py`.
- `docs/EVALUATION.md` (protocol, rupee assumptions with justification, negative findings), `docs/STAGE_03.md`.
- Tests for all of the above, including a leakage test that rewrites the test split and a power check that does the same to validation.

### Changed
- Settings: neg_sample_frac, review/false-positive cost, loss capture rate, ring tau and minimum size, and the Stage 03 output paths; `.env.example` lists the new names.
- `requirements.txt`: pins `joblib==1.6.0` (already installed as a scikit-learn dependency; now imported directly). networkx is still not used or pinned.

## v0.3.0 - Stage 02: noise layer, graph with hub control, features (pending owner confirmation)

### Added
- `backend/ringsentinel/noise.py`: label-blind derived device, IP and VPA-handle attributes with an independence report.
- `backend/ringsentinel/graph/`: transfer graph builder, IDF weights and degree cap, pruning report, communities (components plus Louvain), giant-component ablation.
- `backend/ringsentinel/features/`: node and community features; `backend/ringsentinel/stage02.py` orchestration.
- `scripts/run_stage02.py`, `scripts/ablation_giant_component.py`.
- Tests for all of the above (132 tests in total after this stage).

### Changed
- Settings: `hub_cap`, `attr_cap`, `community_cap`, `louvain_resolution` and the Stage 02 output paths.
- `requirements.txt`: adds `igraph==1.0.0` and `scipy==1.16.3` (both have wheels for Python 3.11 to 3.13 on Windows and Linux). networkx is not used yet and is not pinned.

## v0.2.0 - Stage 01: data, temporal split and baselines

### Added
- `scripts/inspect_schema.py`: assumption-free schema inspector for the raw files, with tests.
- Ingestion (`backend/ringsentinel/ingest/`): header check, checksum manifest, patterns parser, chunked normalizer with pattern-derived labels and an INR amount.
- `backend/ringsentinel/split.py`: leakage-free temporal split with ring assignment.
- `backend/ringsentinel/models/baselines.py`: velocity rule and tabular XGBoost baselines.
- `backend/ringsentinel/evaluation/metrics.py`: precision, recall, F1, PR-AUC, best-F1 threshold.
- `scripts/run_stage01.py`: verify, ingest, split, baselines in one command.
- `docs/DATA.md`, `data/raw/MANIFEST.json`, `config/fx_rates_inr.json` (placeholder rates).

- `backend/ringsentinel/ingest/diagnose.py` and `scripts/diagnose_matching.py`: read-only diagnostic for pattern-to-CSV matching failures, with tests.

### Changed
- Corrected HI-Small download (adds the `Is Laundering` column): manifest checksums refreshed, `is_illicit` now comes from that column, label note in `baseline_metrics.json` now reads the real label source, stale "no label column" statements removed from code and docs, real-data header test accepts both layouts.
- Settings gain split fractions and per-variant file paths; version 0.2.0.
- Pinned numpy, pandas, pyarrow, scikit-learn and xgboost.

## v0.1.0 - Stage 00: environment and scaffold

### Added
- Repository layout, pinned `requirements.txt`, `pyproject.toml` (pytest and ruff config).
- `backend/ringsentinel/config.py`: validated settings with a single dataset-variant switch (HI-Small default; HI-Medium supported without code changes).
- `scripts/check_docs.py` and its tests: fails when docs name a missing file or function.
- GitHub Actions workflow running ruff, check_docs and pytest on Ubuntu and Windows.
- Docs skeleton: README, ARCHITECTURE, PROJECT_EXPLAINER, STAGE_00, HANDOVER.
- `.gitignore`, `.gitattributes` (LF line endings), `.env.example` (names only).
- Frontend shell `frontend/package.json` (no dependencies yet).
