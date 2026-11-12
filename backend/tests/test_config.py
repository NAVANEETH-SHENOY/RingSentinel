"""Guards the dataset-variant switch (Small now, Medium later without code changes)."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from ringsentinel.config import PROJECT_ROOT, Settings, get_settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("RS_DATASET_VARIANT", "RS_DATA_DIR", "RS_SEED"):
        monkeypatch.delenv(name, raising=False)


def test_defaults():
    s = get_settings(load_env_file=False)
    assert s.dataset_variant == "HI-Small"
    assert s.seed == 42
    assert s.data_dir == PROJECT_ROOT / "data"


def test_variant_override_changes_paths(monkeypatch):
    monkeypatch.setenv("RS_DATASET_VARIANT", "HI-Medium")
    s = get_settings(load_env_file=False)
    assert s.dataset_variant == "HI-Medium"
    assert s.variant_slug == "hi_medium"
    assert s.processed_dir.name == "hi_medium"


def test_small_and_medium_do_not_share_processed_dir():
    small = Settings(dataset_variant="HI-Small")
    medium = Settings(dataset_variant="HI-Medium")
    assert small.processed_dir != medium.processed_dir
    assert small.raw_dir == medium.raw_dir


def test_invalid_variant_rejected(monkeypatch):
    monkeypatch.setenv("RS_DATASET_VARIANT", "HI-Large")
    with pytest.raises(ValidationError):
        get_settings(load_env_file=False)


def test_blank_values_are_treated_as_unset(monkeypatch):
    monkeypatch.setenv("RS_DATASET_VARIANT", "")
    monkeypatch.setenv("RS_DATA_DIR", "")
    monkeypatch.setenv("RS_SEED", "")
    s = get_settings(load_env_file=False)
    assert s.dataset_variant == "HI-Small"
    assert s.seed == 42


def test_data_dir_and_seed_override(monkeypatch, tmp_path):
    monkeypatch.setenv("RS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RS_SEED", "7")
    s = get_settings(load_env_file=False)
    assert s.data_dir == Path(tmp_path)
    assert s.seed == 7
    assert s.snapshots_dir == Path(tmp_path) / "snapshots"
