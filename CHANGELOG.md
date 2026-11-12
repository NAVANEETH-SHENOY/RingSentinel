# Changelog

One entry per tag. Format: Keep a Changelog style, Conventional Commit prefixes.

## v0.1.0 - Stage 00: environment and scaffold

### Added
- Repository layout, pinned `requirements.txt`, `pyproject.toml` (pytest and ruff config).
- `backend/ringsentinel/config.py`: validated settings with a single dataset-variant switch (HI-Small default; HI-Medium supported without code changes).
- `scripts/check_docs.py` and its tests: fails when docs name a missing file or function.
- GitHub Actions workflow running ruff, check_docs and pytest on Ubuntu and Windows.
- Docs skeleton: README, ARCHITECTURE, PROJECT_EXPLAINER, STAGE_00, HANDOVER.
- `.gitignore`, `.gitattributes` (LF line endings), `.env.example` (names only).
- Frontend shell `frontend/package.json` (no dependencies yet).
