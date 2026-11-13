# Changes: Stage 01 diagnostic addendum

ADDED
- backend/ringsentinel/ingest/diagnose.py
- scripts/diagnose_matching.py
- backend/tests/test_diagnose.py
- CHANGES_STAGE_01_DIAGNOSTIC.md

MODIFIED
- docs/PROJECT_EXPLAINER.md (repo map, debugging playbook)
- docs/STAGE_01.md (diagnosing a matching failure)
- CHANGELOG.md
- backend/ringsentinel/ingest/normalize.py (adds check_sender_accounts(); matching and labelling unchanged)
- backend/tests/test_diagnose.py is ADDED, see above

DELETE (manual)
- none

No change to matching or labelling. One validation was ADDED (sender account integrity); none was weakened.
