"""API settings from the environment, and the rate limiter on its own."""

import pytest
from app.config import AppSettings, load_app_settings
from app.ratelimit import MAX_TRACKED_KEYS, WINDOW_SECONDS, RateLimiter
from pydantic import ValidationError

NAMES = (
    "RS_DATA_DIR", "RS_SNAPSHOT_DIR", "RS_AUDIT_DB_URL", "RS_ANALYST_TOKEN", "RS_CORS_ORIGINS",
    "RS_RATE_LIMIT_READ_PER_MIN", "RS_RATE_LIMIT_WRITE_PER_MIN", "RS_DATASET_VARIANT",
)  # fmt: skip


@pytest.fixture
def clean_env(monkeypatch):
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_defaults_derive_from_the_data_dir(clean_env, tmp_path):
    clean_env.setenv("RS_DATA_DIR", str(tmp_path))
    s = load_app_settings(load_env_file=False)
    assert s.snapshot_dir == tmp_path / "snapshots"
    assert s.audit_db_url == f"sqlite:///{(tmp_path / 'audit' / 'audit.sqlite3').as_posix()}"
    assert s.analyst_token is None and s.cors_origins == ("http://localhost:3000",)
    assert (s.rate_limit_read_per_min, s.rate_limit_write_per_min) == (120, 20)


def test_every_variable_is_read(clean_env, tmp_path):
    clean_env.setenv("RS_SNAPSHOT_DIR", str(tmp_path / "snap"))
    clean_env.setenv("RS_AUDIT_DB_URL", "sqlite:///:memory:")
    clean_env.setenv("RS_ANALYST_TOKEN", "x" * 20)
    clean_env.setenv("RS_CORS_ORIGINS", "https://a.example, https://b.example ,")
    clean_env.setenv("RS_RATE_LIMIT_READ_PER_MIN", "5")
    clean_env.setenv("RS_RATE_LIMIT_WRITE_PER_MIN", "0")
    s = load_app_settings(load_env_file=False)
    assert s.snapshot_dir == tmp_path / "snap" and s.audit_db_url == "sqlite:///:memory:"
    assert s.analyst_token == "x" * 20
    assert s.cors_origins == ("https://a.example", "https://b.example")
    assert (s.rate_limit_read_per_min, s.rate_limit_write_per_min) == (5, 0)


def test_blank_values_count_as_unset(clean_env):
    for name in ("RS_ANALYST_TOKEN", "RS_CORS_ORIGINS", "RS_RATE_LIMIT_READ_PER_MIN"):
        clean_env.setenv(name, "   ")
    s = load_app_settings(load_env_file=False)
    assert s.analyst_token is None and s.rate_limit_read_per_min == 120


def test_weak_token_wildcard_cors_and_negative_limits_are_refused(clean_env, tmp_path):
    base = {"snapshot_dir": tmp_path, "audit_db_url": "sqlite:///:memory:"}
    with pytest.raises(ValidationError, match="16 characters"):
        AppSettings(**base, analyst_token="short")
    with pytest.raises(ValidationError, match="explicit origins"):
        AppSettings(**base, cors_origins=("*",))
    with pytest.raises(ValidationError, match="off"):
        AppSettings(**base, rate_limit_read_per_min=-1)


def test_the_token_is_not_shown_in_repr(tmp_path):
    s = AppSettings(
        snapshot_dir=tmp_path, audit_db_url="sqlite:///:memory:", analyst_token="s" * 20
    )
    assert "s" * 20 not in repr(s)


# ------------------------------------------------------------------- rate limiter
def test_limiter_allows_up_to_the_limit_then_reports_the_wait():
    now = [100.0]
    lim = RateLimiter({"read": 2}, clock=lambda: now[0])
    assert lim.check("1.1.1.1", "read") is None
    now[0] += 10
    assert lim.check("1.1.1.1", "read") is None
    wait = lim.check("1.1.1.1", "read")
    assert wait == pytest.approx(WINDOW_SECONDS - 10)
    now[0] += wait
    assert lim.check("1.1.1.1", "read") is None  # the oldest hit has aged out


def test_limiter_keeps_clients_and_buckets_apart_and_zero_means_off():
    lim = RateLimiter({"read": 1, "write": 0})
    assert lim.check("a", "read") is None and lim.check("a", "read") is not None
    assert lim.check("b", "read") is None
    for _ in range(50):
        assert lim.check("a", "write") is None


def test_limiter_does_not_grow_without_bound():
    now = [0.0]
    lim = RateLimiter({"read": 1}, clock=lambda: now[0])
    for i in range(MAX_TRACKED_KEYS + 50):
        lim.check(f"c{i}", "read")
    now[0] += WINDOW_SECONDS + 1
    lim.check("late", "read")
    assert len(lim._hits) < 100
