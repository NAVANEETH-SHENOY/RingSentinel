"""Guards the Stage 03 settings, cost defaults and output paths."""

import pytest
from pydantic import ValidationError
from ringsentinel.config import Settings, get_settings

NAMES = (
    "RS_DATASET_VARIANT", "RS_DATA_DIR", "RS_NEG_SAMPLE_FRAC", "RS_REVIEW_COST_INR",
    "RS_FP_COST_INR", "RS_LOSS_CAPTURE_RATE", "RS_RING_TAU", "RS_RING_MIN_SIZE",
)  # fmt: skip


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)


def test_defaults_are_the_agreed_rupee_assumptions():
    s = get_settings(load_env_file=False)
    assert (s.review_cost_inr, s.fp_cost_inr, s.loss_capture_rate) == (250.0, 500.0, 1.0)
    assert s.ring_tau == 0.5 and s.ring_min_size == 3 and s.neg_sample_frac == 0.2


def test_env_overrides_and_blank_means_unset(monkeypatch):
    monkeypatch.setenv("RS_FP_COST_INR", "750")
    monkeypatch.setenv("RS_RING_MIN_SIZE", "4")
    monkeypatch.setenv("RS_REVIEW_COST_INR", "")
    s = get_settings(load_env_file=False)
    assert s.fp_cost_inr == 750.0 and s.ring_min_size == 4 and s.review_cost_inr == 250.0


@pytest.mark.parametrize(
    "field, value",
    [
        ("neg_sample_frac", 0.0), ("neg_sample_frac", 1.5), ("review_cost_inr", -1.0),
        ("fp_cost_inr", -1.0), ("loss_capture_rate", 0.0), ("loss_capture_rate", 2.0),
        ("ring_tau", 0.0), ("ring_min_size", 1),
    ],
)  # fmt: skip
def test_invalid_values_are_rejected(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_stage03_paths_live_in_the_variant_folder():
    small, medium = Settings(dataset_variant="HI-Small"), Settings(dataset_variant="HI-Medium")
    names = ("scores_path", "metrics_path", "rings_path", "ablations_path", "robustness_path",
             "latency_path", "models_dir", "features_nohub_path")  # fmt: skip
    for name in names:
        assert getattr(small, name).parent == small.processed_dir
        assert getattr(small, name) != getattr(medium, name)
