"""Deployment files: requirements-api.txt matches requirements.txt and is enough to serve,
render.yaml carries no secret, and the committed bundle is what the API and the frontend serve."""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HEAVY = ("sklearn", "xgboost", "pyarrow", "scipy", "igraph", "joblib", "torch")


def pins(path: Path) -> dict[str, str]:
    found = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.\-]+)(\[[a-z,]+\])?==([0-9][^\s#]*)", line.strip())
        if m:
            found[m.group(1).lower()] = m.group(3)
    return found


def test_api_requirements_are_pinned_and_agree_with_the_full_set():
    api, full = pins(ROOT / "requirements-api.txt"), pins(ROOT / "requirements.txt")
    assert {"fastapi", "uvicorn", "pydantic", "psycopg", "pandas", "numpy"} <= set(api)
    for name, version in api.items():
        assert full.get(name) == version, f"{name}: requirements-api {version} vs {full.get(name)}"


def test_api_requirements_leave_out_the_modelling_stack_and_dev_tools():
    api = set(pins(ROOT / "requirements-api.txt"))
    assert not api & {"scikit-learn", "xgboost", "pyarrow", "scipy", "igraph", "pytest", "ruff"}


def test_the_api_imports_and_serves_without_the_modelling_stack():
    """Blocks the heavy packages, then builds the app on the committed bundle and calls it."""
    code = f"""
import sys
for name in {HEAVY!r}:
    sys.modules[name] = None  # any import of them now raises ImportError
sys.path.insert(0, {str(ROOT / "backend")!r})
from fastapi.testclient import TestClient
from app.config import AppSettings
from app.main import create_app
import tempfile, pathlib
tmp = pathlib.Path(tempfile.mkdtemp())
settings = AppSettings(snapshot_dir=pathlib.Path({str(ROOT / "data" / "snapshots")!r}),
    audit_db_url="sqlite:///" + (tmp / "a.sqlite3").as_posix(), docs_enabled=False)
client = TestClient(create_app(settings))
assert client.get("/api/v1/live").json() == {{"status": "ok"}}
assert client.get("/api/v1/queue").status_code == 200
print("SLIM-OK")
"""
    run = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=120
    )
    assert run.returncode == 0 and "SLIM-OK" in run.stdout, run.stderr[-800:]


def render_text() -> str:
    return (ROOT / "render.yaml").read_text(encoding="utf-8")


def test_render_blueprint_is_a_free_python_service_with_a_db_free_health_check():
    text = render_text()
    assert re.search(r"^\s*plan: free\s*$", text, re.M)
    assert re.search(r"^\s*runtime: python\s*$", text, re.M)
    assert re.search(r"^\s*healthCheckPath: /api/v1/live\s*$", text, re.M)
    assert "requirements-api.txt" in text and "--factory app.main:create_app" in text
    assert "$PORT" in text
    # Render needs a fully qualified version such as 3.13.5
    assert re.search(r"PYTHON_VERSION\s*\n\s*value: \d+\.\d+\.\d+\s*$", text, re.M)


def test_render_blueprint_holds_no_secret_and_asks_for_the_three_that_matter():
    text = render_text()
    for name in ("RS_AUDIT_DB_URL", "RS_ANALYST_TOKEN", "RS_CORS_ORIGINS"):
        assert re.search(rf"key: {name}\s*\n\s*sync: false", text), name
    assert not re.search(r"postgres(ql)?://\S+@", text)
    assert not re.search(r"gsk_|AIza|sk-", text)
    assert 'key: RS_API_DOCS\n        value: "0"' in text


def test_vercel_config_is_valid_json_with_security_headers():
    config = json.loads((ROOT / "frontend" / "vercel.json").read_text(encoding="utf-8"))
    keys = {h["key"] for rule in config["headers"] for h in rule["headers"]}
    assert {"X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy"} <= keys


def test_the_frontend_snapshot_copy_is_the_committed_bundle():
    data, front = ROOT / "data" / "snapshots", ROOT / "frontend" / "public" / "snapshots"
    if not (data / "meta.json").is_file():
        pytest.skip("no committed bundle in this checkout")
    meta = json.loads((data / "meta.json").read_text(encoding="utf-8"))
    for name in ("queue", "cases", "metrics", "meta", "drift", "replay"):
        a, b = ((d / f"{name}.json").read_bytes() for d in (data, front))
        assert a == b, f"{name}.json differs: run scripts\\sync_frontend_snapshots.py"
    for name, digest in meta["files"].items():  # and the files are the ones meta.json describes
        assert hashlib.sha256((front / name).read_bytes()).hexdigest() == digest, name


def test_the_gitignore_does_not_hide_the_deployed_bundle():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "data/audit/" in ignore and ".env" in ignore.splitlines()
    assert not re.search(r"^/?data/snapshots", ignore, re.M)
    assert not re.search(r"^/?frontend/public/snapshots", ignore, re.M)
    front = (ROOT / "frontend" / ".gitignore").read_text(encoding="utf-8")
    live = [ln.strip() for ln in front.splitlines() if ln.strip() and not ln.startswith("#")]
    assert not [ln for ln in live if "snapshots" in ln], "the deployed site needs these committed"
