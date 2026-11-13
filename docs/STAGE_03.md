# Stage 03: Detectors, Ring Extraction, Evaluation

**Tag:** `v0.4.0` (after tests, real-data validation, and merge)  
**Branch:** `stage-03-detectors-evaluation`

## What Was Built

- **D7 — Detectors** (`backend/ringsentinel/detect/`):
  - `backend/ringsentinel/detect/tabular.py` — per-transfer columns and trailing 24-hour counts.
  - `backend/ringsentinel/detect/matrix.py` — design matrices from Stage 02 window features.
  - `backend/ringsentinel/detect/models.py` — XGBoost and Isolation Forest fitting.
  - `backend/ringsentinel/detect/guard.py` — test-split protection.
  - Four detectors: `velocity`, `xgb_tabular`, `xgb_graph`, and `iforest`. See `docs/EVALUATION.md`.

- **D8 — Ring extraction** (`backend/ringsentinel/rings/extract.py`): extracts rings from flagged transfers because Stage 02 showed that whole-graph communities do not reliably recover rings.

- **D9 — Evaluation** (`backend/ringsentinel/evaluate/`):
  - `backend/ringsentinel/evaluate/metrics.py` — PR-AUC, precision, recall, F1, and best-F1 threshold.
  - `backend/ringsentinel/evaluate/ringmatch.py` — Jaccard-based ring matching.
  - `backend/ringsentinel/evaluate/cost.py` — rupee net-value calculation and threshold selection.
  - `backend/ringsentinel/evaluate/report.py` — per-detector reports, cost sweep, and latency.

- **Orchestration** (`backend/ringsentinel/stage03.py`): `run_detect()`, `run_evaluate()`, `run_ablate()`, and `run_robustness()`.

- **Commands**: `scripts/run_stage03.py` runs individual pipeline steps; `scripts/reproduce.py` runs the complete pipeline and checks reproducibility.

- **Settings** (`backend/ringsentinel/config.py`): `RS_NEG_SAMPLE_FRAC`, `RS_REVIEW_COST_INR`, `RS_FP_COST_INR`, `RS_LOSS_CAPTURE_RATE`, `RS_RING_TAU`, `RS_RING_MIN_SIZE`, and Stage 03 output paths.

## How to Run

Run from the Windows CMD project root with the virtual environment active and Stage 01 and Stage 02 outputs present.

```cmd
pip install -r requirements.txt
python scripts\run_stage03.py --step all
python scripts\reproduce.py
```

Individual steps can be run using:

```cmd
python scripts\run_stage03.py --step detect
python scripts\run_stage03.py --step evaluate
python scripts\run_stage03.py --step ablate
python scripts\run_stage03.py --step robustness
```

`scripts/reproduce.py` runs all four steps, writes `docs/EVALUATION_RESULTS.md`, and compares the newly generated `data/processed/hi_small/metrics.json` with the previous run. It reports whether the metrics are identical. If they differ, it exits with code 2 and lists the differences. [generated]

To reuse existing scores and run only evaluation:

```cmd
python scripts\reproduce.py --evaluate-only
```

## Real-Data Execution

Stage 03 has now been executed on the HI-Small dataset on the owner's Windows environment.

- Loaded **5,078,345 events**.
- Test split contained **1,015,882 transfers**, including **1,798 positive transfers**.
- The complete Stage 03 pipeline generated detector scores, evaluation metrics, ring results, ablation results, and robustness results.
- A subsequent `scripts/reproduce.py` run reported that `data/processed/hi_small/metrics.json` was identical to the previous run. [generated]

Exact peak memory and execution time were not formally recorded.

## Results Summary

The following results were obtained from the real HI-Small run.

| Detector | Validation PR-AUC | Test PR-AUC | Test Precision | Test Recall | Test F1 |
|---|---:|---:|---:|---:|---:|
| Velocity | 0.0010 | 0.0014 | 0.0016 | 0.0211 | 0.0030 |
| XGBoost Tabular | 0.1185 | 0.2040 | 0.3203 | 0.3226 | 0.3214 |
| XGBoost Graph | 0.4534 | 0.6145 | 0.6999 | 0.5473 | 0.6142 |
| Isolation Forest | 0.0092 | 0.0052 | 0.0318 | 0.0289 | 0.0303 |

**Important evaluation details:**

- Validation PR-AUC is optimistic because validation data is used for early stopping.
- Classification thresholds are selected using validation data, not test data.
- Test precision, recall, and F1 are transaction-level metrics.
- Ring precision and recall are evaluated separately using ring matching.
- Net value uses the configured rupee cost assumptions and the validation-selected net-value threshold.

The graph-based XGBoost detector achieved the highest test PR-AUC and F1 among the four detectors in this run.

### Ablation Results

| Configuration | Test PR-AUC |
|---|---:|
| Graph features OFF | 0.20404 |
| Graph features ON, hub control OFF | 0.62364 |
| Graph features ON, hub control ON | 0.61450 |

### Robustness Results

| Edge Dropout | Test PR-AUC |
|---|---:|
| 0% | 0.61450 |
| 10% | 0.58031 |
| 20% | 0.51885 |
| 30% | 0.44342 |
| 50% | 0.26897 |

## Outputs

All generated outputs are stored in `data/processed/hi_small/`. [generated]

| File | Content |
|---|---|
| `data/processed/hi_small/scores.parquet` | D7 validation and test rows with one score column per detector [generated] |
| `data/processed/hi_small/models/` | Fitted XGBoost and Isolation Forest models [generated] |
| `data/processed/hi_small/detect_report.json` | Fit information, top features by gain, validation PR-AUC, and Stage 01 reference numbers [generated] |
| `data/processed/hi_small/metrics.json` | D9 transaction and ring metrics, operating points, cost, and sweep [generated] |
| `data/processed/hi_small/rings.json` | D8 extracted test rings with members, scores, and top features [generated] |
| `data/processed/hi_small/latency.json` | Time from a ring's first event to its first flagged transfer [generated] |
| `data/processed/hi_small/ablations.json` | Hub-control and graph-feature ablation results [generated] |
| `data/processed/hi_small/scores_ablation.parquet` | Scores for ablation experiments [generated] |
| `data/processed/hi_small/features_nohub.parquet` | Features rebuilt without hub control [generated] |
| `data/processed/hi_small/robustness.json` | Metric decay under edge dropout [generated] |
| `data/processed/hi_small/results_table.md` | Detector comparison table [generated] |

## Tests

Stage 03 tests are located in `backend/tests/`:

- `backend/tests/test_stage03_metrics.py`
- `backend/tests/test_stage03_rings.py`
- `backend/tests/test_stage03_cost.py`
- `backend/tests/test_stage03_detect.py`
- `backend/tests/test_config_stage03.py`
- `backend/tests/test_stage03_pipeline.py`
- `backend/tests/s03_world.py` (test helper)

They cover metric calculations and scikit-learn cross-checks, ring extraction and Jaccard boundaries, cost arithmetic and threshold selection, trailing counts and prevention of future-information leakage, design matrices, test-split protection, determinism, synthetic end-to-end execution, and robustness at 0% edge dropout.

## Known Limitations

- Stage 01 source files were not included in the incremental Stage 02 package. Stage 03 therefore uses the documented parquet contracts and does not import Stage 01 modules. Its baseline implementations are reimplemented; see Section 2 of `docs/EVALUATION.md`.
- The rupee review and false-positive costs are planning assumptions, not externally sourced financial values.
- FX rates remain placeholders.
- At a loss-capture rate of 1.0, flagging everything can appear profitable. The cost sweep across 36 settings should therefore be considered alongside the default assumptions.
- Strict ring precision is pessimistic because ring matching requires pattern-level agreement. Lenient ring precision is also reported.
- Hub-control-off features are rebuilt from scratch, which adds the cost of another feature-generation step.
- Real-data execution and reproducibility have been verified on the owner's Windows environment, but exact peak memory and runtime measurements remain unrecorded.