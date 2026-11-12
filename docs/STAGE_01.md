# Stage 01: data, temporal split and baselines

Status: **part 1 of 2 delivered** (schema inspector). Part 2 (ingestor, splitter, baselines, metrics, `docs/DATA.md` [planned]) is written only after the real schema is known. Tag v0.2.0 comes after part 2.

## Why two parts

The project rule is to inspect the real dataset schema before coding against it. The build environment cannot reach Kaggle, so the real files cannot be seen here. Instead of guessing column names, part 1 ships a tool that reports them from the owner's machine.

## What part 1 built

- `scripts/inspect_schema.py`: standard-library only (no new dependency). For a transactions CSV it reports header, duplicate header names, row count, ragged rows, per-column empties, numeric and text ranges, up to 50 distinct values per column, whether the first column is in time order, first rows, file size and SHA-256. For the patterns file it reports line counts, the most common non-data lines and prefixes, and the first 40 lines, assuming nothing about the layout.
- `backend/tests/test_inspect_schema.py`: six tests on tiny synthetic files.

## How to run (Windows cmd, repo root, venv active)

```
python scripts\inspect_schema.py --trans data\raw\HI-Small_Trans.csv --patterns data\raw\HI-Small_Patterns.txt
```

The file names above are the expected names and are not confirmed. Use the names you actually downloaded. The report is saved to `data/raw/schema_report.txt` [generated].

## Known limits

- Tested only on synthetic files; not yet run on the real dataset.
- The text-order check compares the first column as text. It is meaningful only if the timestamp format sorts correctly as text (to be confirmed from the report).
