# CHANGES_STAGE_08

## ADDED
- .github/workflows/audit.yml
- backend/ringsentinel/elliptic/ (`__init__.py`, settings.py, schema.py, load.py, split.py, graph.py, pipeline.py, gnn.py, synthetic.py)
- backend/tests/s08_world.py
- backend/tests/test_stage08_load.py, test_stage08_graph.py, test_stage08_pipeline.py, test_stage08_gnn.py, test_stage08_hardening.py, test_stage08_secrets_scan.py
- docs/STAGE_08.md
- requirements-gnn.txt (optional)
- scripts/run_stage08.py
- scripts/secrets_scan.py
- CHANGES_STAGE_08.md

## MODIFIED
- .env.example, .gitignore, CHANGELOG.md, HANDOVER.md, README.md, requirements.txt (pyarrow 23.0.1)
- backend/app/config.py, backend/app/main.py, backend/app/ratelimit.py
- docs/ARCHITECTURE.md, docs/DATA.md, docs/PROJECT_EXPLAINER.md

## DELETE (manual)
- None
