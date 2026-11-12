# Changes in Stage 01 (data, temporal split, baselines)

## Revision 2 (after the real-data run with the corrected HI-Small download)
Apply this zip over the project root. It contains only files that changed after the previous Stage 01 zip.

### ADDED
- backend/tests/test_label_note.py

### MODIFIED (the header-test change in backend/tests/test_real_data.py is already in your copy)
- backend/ringsentinel/stage01.py (baseline note now reads the real label source from the ingest report; it used to say "patterns file only", which was wrong for the corrected CSV)
- backend/ringsentinel/ingest/normalize.py (docstring only)
- backend/ringsentinel/ingest/schema.py (comments only)
- docs/DATA.md, docs/STAGE_01.md, docs/ARCHITECTURE.md, docs/PROJECT_EXPLAINER.md
- HANDOVER.md, CHANGELOG.md, CHANGES_STAGE_01.md

### DELETE (manual)
- None.

### Revision 1 (original Stage 01 zip) follows.

Everything below is relative to the end of Stage 00. Files marked "(part 1)" were already delivered in `ringsentinel_stage_01_schema-inspector.zip`; they are repeated here so this zip is complete on its own.

## ADDED
- scripts/inspect_schema.py (part 1)
- scripts/run_stage01.py
- backend/tests/test_inspect_schema.py (part 1)
- backend/tests/conftest.py
- backend/tests/test_schema_manifest.py
- backend/tests/test_patterns.py
- backend/tests/test_normalize.py
- backend/tests/test_split_metrics.py
- backend/tests/test_baselines_stage01.py
- backend/tests/test_real_data.py
- backend/ringsentinel/ingest/__init__.py
- backend/ringsentinel/ingest/schema.py
- backend/ringsentinel/ingest/manifest.py
- backend/ringsentinel/ingest/patterns.py
- backend/ringsentinel/ingest/normalize.py
- backend/ringsentinel/split.py
- backend/ringsentinel/stage01.py
- backend/ringsentinel/evaluation/__init__.py
- backend/ringsentinel/evaluation/metrics.py
- backend/ringsentinel/models/__init__.py
- backend/ringsentinel/models/baselines.py
- config/fx_rates_inr.json
- data/raw/MANIFEST.json
- docs/DATA.md
- docs/STAGE_01.md (first draft in part 1, rewritten here)
- CHANGES_STAGE_01.md

## MODIFIED
- requirements.txt (adds numpy, pandas, pyarrow, scikit-learn, xgboost)
- backend/ringsentinel/__init__.py (version 0.2.0)
- backend/ringsentinel/config.py (split fractions, per-variant file paths)
- backend/tests/test_smoke.py (version)
- backend/tests/test_config.py (new settings)
- .env.example (RS_TRAIN_FRAC, RS_VAL_FRAC)
- README.md, CHANGELOG.md, HANDOVER.md
- docs/ARCHITECTURE.md, docs/PROJECT_EXPLAINER.md

## DELETE (manual)
- None.
