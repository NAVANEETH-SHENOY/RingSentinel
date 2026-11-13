"""Central configuration. Every stage reads settings through get_settings().

The dataset variant is one setting (RS_DATASET_VARIANT). All data paths derive from it,
so switching from HI-Small to HI-Medium needs no code change.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, field_validator, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]

SUPPORTED_VARIANTS = ("HI-Small", "LI-Small", "HI-Medium", "LI-Medium")
DEFAULT_VARIANT = "HI-Small"
DEFAULT_SEED = 42
DEFAULT_TRAIN_FRAC = 0.6
DEFAULT_VAL_FRAC = 0.2
DEFAULT_HUB_CAP = 50  # fallback only; Stage 02 tunes the cap on the validation window
DEFAULT_ATTR_CAP = 50
DEFAULT_COMMUNITY_CAP = 200
DEFAULT_LOUVAIN_RESOLUTION = 1.0
# Stage 03 defaults (planning assumptions, see docs/EVALUATION.md)
DEFAULT_NEG_SAMPLE_FRAC = 0.2
DEFAULT_REVIEW_COST_INR = 250.0
DEFAULT_FP_COST_INR = 500.0
DEFAULT_LOSS_CAPTURE_RATE = 1.0
DEFAULT_RING_TAU = 0.5
DEFAULT_RING_MIN_SIZE = 3


class Settings(BaseModel):
    """Validated runtime settings."""

    dataset_variant: str = DEFAULT_VARIANT
    data_dir: Path = PROJECT_ROOT / "data"
    seed: int = DEFAULT_SEED
    train_frac: float = DEFAULT_TRAIN_FRAC
    val_frac: float = DEFAULT_VAL_FRAC
    # Stage 02. hub_cap None means: use the value tuned on validation (hub_cap_tuning.json),
    # else DEFAULT_HUB_CAP.
    hub_cap: int | None = None
    attr_cap: int = DEFAULT_ATTR_CAP
    community_cap: int = DEFAULT_COMMUNITY_CAP
    louvain_resolution: float = DEFAULT_LOUVAIN_RESOLUTION
    # Stage 03. Share of negative training rows kept when fitting (all positives are kept).
    neg_sample_frac: float = DEFAULT_NEG_SAMPLE_FRAC
    # Cost model (rupees). Planning assumptions, not measured values.
    review_cost_inr: float = DEFAULT_REVIEW_COST_INR
    fp_cost_inr: float = DEFAULT_FP_COST_INR
    loss_capture_rate: float = DEFAULT_LOSS_CAPTURE_RATE
    # Ring-level match: predicted ring is a true positive at Jaccard >= ring_tau.
    ring_tau: float = DEFAULT_RING_TAU
    ring_min_size: int = DEFAULT_RING_MIN_SIZE

    @field_validator("dataset_variant")
    @classmethod
    def _check_variant(cls, value: str) -> str:
        if value not in SUPPORTED_VARIANTS:
            raise ValueError(
                f"Unsupported dataset variant {value!r}. Choose one of {SUPPORTED_VARIANTS}."
            )
        return value

    @model_validator(mode="after")
    def _check_fractions(self) -> Settings:
        if not (0 < self.train_frac < 1 and 0 < self.val_frac < 1):
            raise ValueError("train_frac and val_frac must each be between 0 and 1.")
        if self.train_frac + self.val_frac >= 1:
            raise ValueError("train_frac + val_frac must be below 1 so a test split remains.")
        if self.hub_cap is not None and self.hub_cap < 2:
            raise ValueError("hub_cap must be at least 2.")
        if self.attr_cap < 2 or self.community_cap < 2:
            raise ValueError("attr_cap and community_cap must be at least 2.")
        if self.louvain_resolution <= 0:
            raise ValueError("louvain_resolution must be positive.")
        if not 0 < self.neg_sample_frac <= 1:
            raise ValueError("neg_sample_frac must be in (0, 1].")
        if self.review_cost_inr < 0 or self.fp_cost_inr < 0:
            raise ValueError("review_cost_inr and fp_cost_inr must not be negative.")
        if not 0 < self.loss_capture_rate <= 1:
            raise ValueError("loss_capture_rate must be in (0, 1].")
        if not 0 < self.ring_tau <= 1:
            raise ValueError("ring_tau must be in (0, 1].")
        if self.ring_min_size < 2:
            raise ValueError("ring_min_size must be at least 2.")
        return self

    @property
    def variant_slug(self) -> str:
        """Filesystem-safe form, e.g. 'hi_small'."""
        return self.dataset_variant.lower().replace("-", "_")

    # ---- raw inputs (data/raw) ----
    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def trans_path(self) -> Path:
        """Expected raw transactions file name (confirmed for HI-Small; others assumed)."""
        return self.raw_dir / f"{self.dataset_variant}_Trans.csv"

    @property
    def patterns_path(self) -> Path:
        return self.raw_dir / f"{self.dataset_variant}_Patterns.txt"

    @property
    def manifest_path(self) -> Path:
        return self.raw_dir / "MANIFEST.json"

    # ---- processed outputs (data/processed/<variant>) ----
    @property
    def processed_dir(self) -> Path:
        """Per-variant processed folder so Small and Medium outputs never collide."""
        return self.data_dir / "processed" / self.variant_slug

    @property
    def events_path(self) -> Path:
        return self.processed_dir / "events.parquet"

    @property
    def rings_truth_path(self) -> Path:
        return self.processed_dir / "rings_truth.parquet"

    @property
    def ingest_report_path(self) -> Path:
        return self.processed_dir / "ingest_report.json"

    @property
    def split_path(self) -> Path:
        return self.processed_dir / "split.parquet"

    @property
    def split_meta_path(self) -> Path:
        return self.processed_dir / "split_meta.json"

    @property
    def baseline_metrics_path(self) -> Path:
        return self.processed_dir / "baseline_metrics.json"

    # ---- Stage 02 outputs ----
    @property
    def noise_path(self) -> Path:
        return self.processed_dir / "noise.parquet"

    @property
    def noise_report_path(self) -> Path:
        return self.processed_dir / "noise_report.json"

    @property
    def hub_cap_tuning_path(self) -> Path:
        return self.processed_dir / "hub_cap_tuning.json"

    @property
    def pruning_report_path(self) -> Path:
        return self.processed_dir / "pruning_report.json"

    @property
    def community_report_path(self) -> Path:
        return self.processed_dir / "community_report.json"

    @property
    def features_path(self) -> Path:
        return self.processed_dir / "features.parquet"

    @property
    def ablation_path(self) -> Path:
        return self.processed_dir / "ablation_giant_component.json"

    # ---- Stage 03 outputs ----
    @property
    def models_dir(self) -> Path:
        return self.processed_dir / "models"

    @property
    def scores_path(self) -> Path:
        return self.processed_dir / "scores.parquet"

    @property
    def scores_ablation_path(self) -> Path:
        return self.processed_dir / "scores_ablation.parquet"

    @property
    def features_nohub_path(self) -> Path:
        return self.processed_dir / "features_nohub.parquet"

    @property
    def detect_report_path(self) -> Path:
        return self.processed_dir / "detect_report.json"

    @property
    def metrics_path(self) -> Path:
        return self.processed_dir / "metrics.json"

    @property
    def rings_path(self) -> Path:
        return self.processed_dir / "rings.json"

    @property
    def ablations_path(self) -> Path:
        return self.processed_dir / "ablations.json"

    @property
    def robustness_path(self) -> Path:
        return self.processed_dir / "robustness.json"

    @property
    def latency_path(self) -> Path:
        return self.processed_dir / "latency.json"

    @property
    def results_table_path(self) -> Path:
        return self.processed_dir / "results_table.md"

    @property
    def snapshots_dir(self) -> Path:
        return self.data_dir / "snapshots"

    @property
    def fx_rates_path(self) -> Path:
        return PROJECT_ROOT / "config" / "fx_rates_inr.json"


def get_settings(load_env_file: bool = True) -> Settings:
    """Build Settings from environment variables (and .env if present).

    Empty values are treated as unset, so .env.example can list blank placeholders.
    """
    if load_env_file:
        load_dotenv(PROJECT_ROOT / ".env", override=False)

    values: dict[str, object] = {}
    variant = os.environ.get("RS_DATASET_VARIANT", "").strip()
    if variant:
        values["dataset_variant"] = variant
    data_dir = os.environ.get("RS_DATA_DIR", "").strip()
    if data_dir:
        values["data_dir"] = Path(data_dir)
    seed = os.environ.get("RS_SEED", "").strip()
    if seed:
        values["seed"] = int(seed)
    train_frac = os.environ.get("RS_TRAIN_FRAC", "").strip()
    if train_frac:
        values["train_frac"] = float(train_frac)
    val_frac = os.environ.get("RS_VAL_FRAC", "").strip()
    if val_frac:
        values["val_frac"] = float(val_frac)
    for env_name, field, cast in (
        ("RS_HUB_CAP", "hub_cap", int),
        ("RS_ATTR_CAP", "attr_cap", int),
        ("RS_COMMUNITY_CAP", "community_cap", int),
        ("RS_LOUVAIN_RESOLUTION", "louvain_resolution", float),
        ("RS_NEG_SAMPLE_FRAC", "neg_sample_frac", float),
        ("RS_REVIEW_COST_INR", "review_cost_inr", float),
        ("RS_FP_COST_INR", "fp_cost_inr", float),
        ("RS_LOSS_CAPTURE_RATE", "loss_capture_rate", float),
        ("RS_RING_TAU", "ring_tau", float),
        ("RS_RING_MIN_SIZE", "ring_min_size", int),
    ):
        raw = os.environ.get(env_name, "").strip()
        if raw:
            values[field] = cast(raw)
    return Settings(**values)
