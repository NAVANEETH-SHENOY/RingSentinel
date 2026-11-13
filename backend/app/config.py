"""API settings from environment variables (names listed in .env.example)."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field, field_validator
from ringsentinel.config import PROJECT_ROOT, get_settings

DEFAULT_CORS = "http://localhost:3000"


class AppSettings(BaseModel):
    snapshot_dir: Path
    analyst_token: str | None = Field(default=None, repr=False)
    audit_db_url: str
    cors_origins: tuple[str, ...] = (DEFAULT_CORS,)
    rate_limit_read_per_min: int = 120
    rate_limit_write_per_min: int = 20

    @field_validator("rate_limit_read_per_min", "rate_limit_write_per_min")
    @classmethod
    def _non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("rate limits must be 0 (off) or positive")
        return value

    @field_validator("analyst_token")
    @classmethod
    def _token_strength(cls, value: str | None) -> str | None:
        if value is not None and len(value) < 16:
            raise ValueError("RS_ANALYST_TOKEN must be at least 16 characters")
        return value

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(o.strip() == "*" for o in value):
            raise ValueError("RS_CORS_ORIGINS must list explicit origins, not *")
        return value


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def load_app_settings(load_env_file: bool = True) -> AppSettings:
    """Read RS_* variables. Empty values count as unset."""
    core = get_settings(load_env_file=load_env_file)
    values: dict[str, object] = {
        "snapshot_dir": Path(_env("RS_SNAPSHOT_DIR") or core.snapshots_dir),
        "audit_db_url": _env("RS_AUDIT_DB_URL")
        or f"sqlite:///{(core.data_dir / 'audit' / 'audit.sqlite3').as_posix()}",
    }
    if _env("RS_ANALYST_TOKEN"):
        values["analyst_token"] = _env("RS_ANALYST_TOKEN")
    if _env("RS_CORS_ORIGINS"):
        parts = _env("RS_CORS_ORIGINS").split(",")
        values["cors_origins"] = tuple(o.strip() for o in parts if o.strip())
    for env_name, field in (
        ("RS_RATE_LIMIT_READ_PER_MIN", "rate_limit_read_per_min"),
        ("RS_RATE_LIMIT_WRITE_PER_MIN", "rate_limit_write_per_min"),
    ):
        if _env(env_name):
            values[field] = int(_env(env_name))
    return AppSettings(**values)


__all__ = ["AppSettings", "PROJECT_ROOT", "load_app_settings"]
