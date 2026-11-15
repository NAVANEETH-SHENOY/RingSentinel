"""Shared builder for the Stage 07 tests: the Stage 03 synthetic world, scored and exported."""

from pathlib import Path

from ringsentinel import stage02, stage03
from ringsentinel.config import Settings
from ringsentinel.snapshots.export import export_snapshots
from s03_world import write_world


def build_world(root: Path, **overrides) -> Settings:
    """Run Stages 02 and 03 on the synthetic world. Returns the settings (data under root)."""
    values = {"data_dir": root / "data", "drift_min_events": 50}
    values.update(overrides)
    settings = Settings(**values)
    write_world(settings)
    stage02.run_features(settings)
    stage03.run_detect(settings)
    stage03.run_evaluate(settings)
    stage03.run_ablate(settings)
    stage03.run_robustness(settings)
    return settings


def build_bundle(settings: Settings, out: Path, **kw):
    return export_snapshots(settings, out, git_commit="cafe", **kw)
