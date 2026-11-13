# CHANGES_STAGE_02

Unzip into the project root (overwrites safely). No data, no `.env`.

## ADDED
- backend/ringsentinel/noise.py
- backend/ringsentinel/graph/__init__.py, hubs.py, build.py, communities.py, ablation.py
- backend/ringsentinel/features/__init__.py, node.py, community.py, build.py
- backend/ringsentinel/stage02.py
- scripts/run_stage02.py, scripts/ablation_giant_component.py
- backend/tests/toy_events.py, test_hubs.py, test_graph_build.py, test_communities.py, test_noise.py, test_features.py, test_ablation.py, test_stage02_pipeline.py
- docs/STAGE_02.md, CHANGES_STAGE_02.md

## MODIFIED
- requirements.txt (adds igraph==1.0.0, scipy==1.16.3), .env.example
- backend/ringsentinel/config.py, backend/tests/test_config.py
- README.md, CHANGELOG.md, HANDOVER.md
- docs/ARCHITECTURE.md, docs/DATA.md, docs/PROJECT_EXPLAINER.md, docs/STAGE_01.md

## DELETE (manual)
- None
