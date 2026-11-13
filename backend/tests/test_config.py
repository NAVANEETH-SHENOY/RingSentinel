"""Guards the dataset-variant switch (Small now, Medium later without code changes)."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from ringsentinel.config import PROJECT_ROOT, Settings, get_settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in (
        "RS_DATASET_VARIANT",
        "RS_DATA_DIR",
        "RS_SEED",
        "RS_HUB_CAP",
        "RS_ATTR_CAP",
        "RS_COMMUNITY_CAP",
        "RS_LOUVAIN_RESOLUTION",
    ):
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


def test_split_fractions_default_and_validation(monkeypatch):
    s = get_settings(load_env_file=False)
    assert (s.train_frac, s.val_frac) == (0.6, 0.2)
    with pytest.raises(ValidationError):
        Settings(train_frac=0.8, val_frac=0.3)  # leaves no test split
    with pytest.raises(ValidationError):
        Settings(train_frac=0.0)
    monkeypatch.setenv("RS_TRAIN_FRAC", "0.5")
    monkeypatch.setenv("RS_VAL_FRAC", "0.25")
    s = get_settings(load_env_file=False)
    assert (s.train_frac, s.val_frac) == (0.5, 0.25)


def test_file_paths_follow_the_variant():
    small = Settings(dataset_variant="HI-Small")
    medium = Settings(dataset_variant="HI-Medium")
    assert small.trans_path.name == "HI-Small_Trans.csv"
    assert medium.patterns_path.name == "HI-Medium_Patterns.txt"
    assert small.events_path.parent.name == "hi_small"
    assert medium.events_path.parent.name == "hi_medium"
    assert small.manifest_path == medium.manifest_path  # one manifest, one entry per variant


def test_stage02_defaults_and_overrides(monkeypatch):
    s = get_settings(load_env_file=False)
    assert s.hub_cap is None and s.attr_cap == 50 and s.community_cap == 200
    monkeypatch.setenv("RS_HUB_CAP", "20")
    monkeypatch.setenv("RS_COMMUNITY_CAP", "100")
    s = get_settings(load_env_file=False)
    assert s.hub_cap == 20 and s.community_cap == 100
    assert s.features_path.name == "features.parquet"
    assert s.pruning_report_path.parent == s.processed_dir


@pytest.mark.parametrize(
    "field, value",
    [("hub_cap", 1), ("attr_cap", 1), ("community_cap", 1), ("louvain_resolution", 0)],
)
def test_stage02_invalid_values_rejected(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value})
