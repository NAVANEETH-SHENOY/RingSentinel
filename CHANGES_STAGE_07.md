# CHANGES_STAGE_07

Incremental zip: unzip into the root of your repository (main at f42a7e2, Stage 06 merged, including your Groq changes). Only files that are new or differ from that commit are included; none of your Stage 05 or Stage 06 code was replaced except where listed below. No data, no `.env`, no `node_modules`.

## MODIFIED (28)
- .env.example
- CHANGELOG.md
- HANDOVER.md
- README.md
- backend/app/config.py
- backend/app/routes.py
- backend/ringsentinel/config.py
- backend/ringsentinel/snapshots/export.py
- backend/ringsentinel/snapshots/schemas.py
- docs/ARCHITECTURE.md
- docs/PROJECT_EXPLAINER.md
- docs/STAGE_04.md
- docs/STAGE_05.md
- frontend/public/demo-snapshots/cases.json
- frontend/public/demo-snapshots/drift.json
- frontend/public/demo-snapshots/meta.json
- frontend/public/demo-snapshots/replay.json
- frontend/src/components/AppShell.tsx
- frontend/src/components/CaseView.tsx
- frontend/src/components/QueueView.tsx
- frontend/src/components/ReplayView.tsx
- frontend/src/lib/http.ts
- frontend/src/lib/source.ts
- frontend/src/lib/types.ts
- frontend/src/lib/useResource.ts
- frontend/tests/pages.test.tsx
- scripts/export_snapshots.py
- scripts/make_demo_bundle.py

## ADDED (24)
- CHANGES_STAGE_07.md
- backend/ringsentinel/monitor/__init__.py
- backend/ringsentinel/monitor/drift.py
- backend/ringsentinel/monitor/replay.py
- backend/ringsentinel/review/__init__.py
- backend/ringsentinel/review/feedback.py
- backend/tests/s07_world.py
- backend/tests/test_stage07_api.py
- backend/tests/test_stage07_drift.py
- backend/tests/test_stage07_export.py
- backend/tests/test_stage07_feedback.py
- backend/tests/test_stage07_replay.py
- docs/STAGE_07.md
- docs/screenshots/drift.png
- docs/screenshots/replay.png
- frontend/src/app/drift/page.tsx
- frontend/src/components/ActionPanel.tsx
- frontend/src/components/DriftView.tsx
- frontend/src/components/FeedbackCard.tsx
- frontend/src/components/monitorCharts.tsx
- frontend/src/lib/idempotency.ts
- frontend/src/lib/liveQueue.ts
- frontend/src/lib/replayView.ts
- frontend/tests/stage07.test.tsx

## DELETE (manual)

None.

## Merge notes

- Your `AiCard` (in `frontend/src/components/CaseView.tsx`) and `frontend/tests/ai_card.test.tsx` are kept. `CaseView.tsx` only gains the decision panel and a quiet refresh.
- `backend/ringsentinel/snapshots/export.py` and `schemas.py` keep your `benign_failure_reason`; `scripts/make_demo_bundle.py` keeps your rounding fixes. Your `ai/` code, `STAGE_06.md` and `CHANGES_STAGE_06.md` are untouched.
- `frontend/public/demo-snapshots/*` is the invented DEMO bundle, regenerated (now with drift, replay and template case files): `python scripts\make_demo_bundle.py`.
- Your local `data/snapshots/` has drift.json and replay.json as `not_built`; re-run `python scripts\export_snapshots.py` once the Stage 03 outputs exist.
