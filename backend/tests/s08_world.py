"""A SYNTHETIC Elliptic-format world for the Stage 08 tests (not real data)."""

from __future__ import annotations

from pathlib import Path

from ringsentinel.config import Settings
from ringsentinel.elliptic.settings import EllipticSettings
from ringsentinel.elliptic.synthetic import write_synthetic_elliptic


def make_settings(tmp: Path, **world) -> tuple[EllipticSettings, dict]:
    raw = tmp / "raw" / "elliptic"
    facts = write_synthetic_elliptic(raw, **world)
    core = Settings(data_dir=tmp, drift_min_events=50)
    return EllipticSettings(core=core, raw_dir=raw), facts
