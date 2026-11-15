"""Stage 09 API changes: a liveness route that never touches the database, the audit backend in
/health, and a clean 503 when a hosted audit database cannot be reached."""

import pytest
from app.audit import AuditUnavailable
from app.config import AppSettings
from app.main import API_VERSION, create_app
from fastapi.testclient import TestClient
from ringsentinel.config import Settings
from ringsentinel.snapshots.export import export_snapshots
from s04_bundle import write_stage03_outputs

TOKEN = "t" * 24
H = {"X-Analyst-Token": TOKEN}


@pytest.fixture(scope="module")
def snapshot_dir(tmp_path_factory):
    root = tmp_path_factory.mktemp("api9")
    s = Settings(data_dir=root / "data")
    write_stage03_outputs(s)
    return export_snapshots(s, root / "snap", git_commit="deadbeef").directory


@pytest.fixture
def client(snapshot_dir, tmp_path):
    settings = AppSettings(
        snapshot_dir=snapshot_dir,
        analyst_token=TOKEN,
        audit_db_url=f"sqlite:///{(tmp_path / 'audit.sqlite3').as_posix()}",
        rate_limit_read_per_min=0,
        rate_limit_write_per_min=0,
    )
    return TestClient(create_app(settings))


class DownAudit:
    """Stands in for a Postgres that is asleep or unreachable: every call fails."""

    backend = "postgres"

    def __getattr__(self, name):
        def fail(*args, **kwargs):
            raise AuditUnavailable("the audit database cannot be reached")

        return fail


def test_version_is_the_release_version():
    assert API_VERSION == "1.0.0"


def test_live_answers_without_the_snapshot_or_the_database(client):
    client.app.state.audit = DownAudit()
    out = client.get("/api/v1/live")
    assert out.status_code == 200 and out.json() == {"status": "ok"}


def test_health_names_the_audit_backend(client):
    assert client.get("/api/v1/health").json()["audit_backend"] == "sqlite"


def test_reads_that_need_the_log_answer_503_with_retry_after_when_it_is_down(client):
    client.app.state.audit = DownAudit()
    for path in ("/api/v1/queue", "/api/v1/health", "/api/v1/audit/verify"):
        out = client.get(path, headers=H)
        assert out.status_code == 503, path
        assert out.headers["retry-after"] == "5"
        assert "cannot be reached" in out.json()["detail"]


def test_endpoints_served_from_the_snapshot_alone_keep_working_when_the_log_is_down(client):
    client.app.state.audit = DownAudit()
    for path in ("/api/v1/metrics", "/api/v1/drift", "/api/v1/replay"):
        assert client.get(path).status_code == 200, path


def test_an_action_answers_503_not_500_when_the_log_is_down(client):
    ring = client.get("/api/v1/queue").json()["items"][0]["ring_id"]
    client.app.state.audit = DownAudit()
    body = {"action": "hold", "analyst": "asha", "note": "", "idempotency_key": "k" * 20}
    out = client.post(f"/api/v1/cases/{ring}/action", json=body, headers=H)
    assert out.status_code == 503 and out.headers["retry-after"] == "5"
