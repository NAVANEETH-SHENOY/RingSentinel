# Stage 01: data, temporal split and baselines

Tag: v0.2.0 (tests and the real-data run confirmed by the owner). Branch: `stage-01-data-baselines`.

## What was built

- **D1 raw files**: `data/raw/MANIFEST.json` holds the size and SHA-256 of the two HI-Small files (taken from the owner's schema report). `scripts/run_stage01.py` verifies them before ingest.
- **D2 normalize**: `backend/ringsentinel/ingest/normalize.py` reads the real 11-column CSV (10 raw columns plus `Is Laundering`; a 10-column file is still accepted) in chunks, keeps ids as strings, sorts by time, adds `amount_inr`, parses the patterns file, matches pattern lines to CSV rows (ring_id, ring_type) and takes `is_illicit` from the CSV label column. Output: `data/processed/hi_small/events.parquet` [generated], `rings_truth.parquet` [generated], `ingest_report.json` [generated].
- **D4 split**: `backend/ringsentinel/split.py` cuts by time (default 60 percent train, 20 percent validation, 20 percent test by row count). A ring belongs to the split of its earliest event.
- **Baselines**: velocity rule (transfers in the previous 24 hours) and tabular XGBoost, in `backend/ringsentinel/models/baselines.py`. Shared metrics in `backend/ringsentinel/evaluation/metrics.py`.
- **Runner**: `scripts/run_stage01.py` (steps verify, ingest, split, baselines).
- **Docs**: `docs/DATA.md` with the real columns and what is and is not verified.

## How to run (Windows cmd, repo root, venv active)

```
pip install -r requirements.txt
python scripts\run_stage01.py
```

Steps can be run separately: `--step verify|ingest|split|baselines`. `--force` redoes ingest. `--write-manifest` records checksums for another variant. The test split is removed before any feature is computed or model fitted.

The XGBoost baseline trains on roughly three million rows with one thread (for reproducibility), so expect several minutes.

## Diagnosing a matching failure

If ingest stops with `N of M pattern lines could not be matched to CSV rows`, run `python scripts\diagnose_matching.py`. It is read-only (it changes no labels and no checks) and writes a text and a JSON report into the processed folder [generated]. It reports progressive match levels, a leave-one-field-out table (the field whose removal lifts the match count is the one that disagrees), per-field value presence, vocabulary differences, and the nearest same-account CSV row with time offsets and amount ratios. `diagnose_legs()` adds an endpoint analysis: it locates each pattern line by ts + amount_received + recv_currency (for comparison only, never for labelling) and classifies how the pattern's sender and receiver relate to the located CSV rows (exact row, endpoints in one row, sender and receiver taken from two different rows, swapped, and so on). The `MAX_UNMATCHED_FRACTION` check stays in force.

## Sender account integrity check

`check_sender_accounts()` runs right after the CSV is read and stops ingest when more than half of the rows have the same sender and receiver account (`MAX_SELF_TRANSFER_FRACTION`). The 50 percent limit is a judgement: the self-transfer format "Reinvestment" alone is about 9.5 percent of rows in the owner's file, so any genuine file should sit far below it. This check only adds a failure; the unmatched-pattern check is unchanged.

## Switching to HI-Medium

Set `RS_DATASET_VARIANT=HI-Medium`, download the HI-Medium transactions and patterns files into `data/raw` (expected names HI-Medium_Trans.csv and HI-Medium_Patterns.txt, assumed, not confirmed), run `python scripts\run_stage01.py --write-manifest`, then run the script normally. Outputs go to their own folder. The reader works in chunks and uses shared categoricals, but Medium (about 32 million rows) has not been run; memory use is unverified.

## Known limits

- **Real-data status.** The owner ran the full pipeline on the corrected HI-Small files (5,078,345 rows, 5,177 positives, 370 rings, 0 unmatched pattern lines). The real-data tests in `backend/tests/test_real_data.py` run only where the raw files exist.
- **Labels versus rings**: labels come from the CSV `Is Laundering` column (5,177 positives); only 3,209 of them sit in a pattern ring. See `docs/DATA.md`.
- **XGBoost is repeatable on one machine, not across machines**: the owner's Windows run gave validation PR-AUC 0.0707 (best iteration 64); a Linux rerun on the same files gave 0.0688 (best iteration 55) and was identical on a second Linux run. The velocity rule matched exactly. Quote the owner's numbers and state the platform.
- **Positive rate drifts upward**: 0.075 percent (train), 0.107 percent (val), 0.177 percent (test).
- **Baseline results (validation, threshold-tuned on validation)**: velocity rule PR-AUC 0.00102 against prevalence 0.00107, i.e. no better than chance; tabular XGBoost PR-AUC 0.0707 (about 66 times prevalence), precision 0.112, recall 0.238. The velocity rule's failure is a documented negative finding.
- **Validation numbers are optimistic**: precision, recall and F1 use a threshold chosen on validation itself, and XGBoost early stopping also watches validation. PR-AUC is threshold-free. These are baseline numbers, not final results; the test split is untouched until Stage 03.
- **FX rates are placeholders** (`config/fx_rates_inr.json`).
- Rows with timestamps after the stated 10 days exist (up to 18 Sep); with a row-count split they fall in test.
- Windows installs of the pinned packages have not been verified by me.
