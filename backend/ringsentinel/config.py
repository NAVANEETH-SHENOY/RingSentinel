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


class Settings(BaseModel):
    """Validated runtime settings."""

    dataset_variant: str = DEFAULT_VARIANT
    data_dir: Path = PROJECT_ROOT / "data"
    seed: int = DEFAULT_SEED
    train_frac: float = DEFAULT_TRAIN_FRAC
    val_frac: float = DEFAULT_VAL_FRAC

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
    return Settings(**values)
