# Stage 00: environment and scaffold

Tag: v0.1.0. Branch: `stage-00-scaffold`.

## What was built

- Repository skeleton with the folders the later stages fill (`backend/`, `frontend/`, `data/`, `docs/`, `scripts/`).
- `backend/ringsentinel/config.py`: `Settings` and `get_settings()`. One setting, `RS_DATASET_VARIANT`, selects the dataset variant (HI-Small by default). Processed outputs go to a per-variant folder, so Small and Medium never overwrite each other.
- `scripts/check_docs.py`: fails when docs reference a missing path or function.
- Tests: `backend/tests/test_smoke.py`, `backend/tests/test_config.py`, `backend/tests/test_check_docs.py`.
- CI workflow `.github/workflows/ci.yml` (ruff, check_docs, pytest on Ubuntu and Windows).
- Documentation skeleton and the first zero-context explainer.

## How to run

Windows cmd, from the repo root:

```
py -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
pytest
ruff check .
python scripts\check_docs.py
```

## Known limits

- No data, graph, model, API or UI code exists yet.
- `requirements.txt` pins only what the scaffold uses (pydantic, python-dotenv, pytest, ruff). Data and ML libraries are pinned in Stage 01 and later, when first needed.
- `frontend/package.json` is a shell with no dependencies. Next.js and React are pinned in Stage 05.
- CI has not been observed running on GitHub yet; it runs on your first push.
- Python 3.10 or newer is assumed (ruff target py310). Your exact version has not been confirmed.
