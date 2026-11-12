"""Central configuration. Every stage reads settings through get_settings().

The dataset variant is one setting (RS_DATASET_VARIANT). All data paths derive from it,
so switching from HI-Small to HI-Medium needs no code change.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, field_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]

SUPPORTED_VARIANTS = ("HI-Small", "LI-Small", "HI-Medium", "LI-Medium")
DEFAULT_VARIANT = "HI-Small"
DEFAULT_SEED = 42


class Settings(BaseModel):
    """Validated runtime settings."""

    dataset_variant: str = DEFAULT_VARIANT
    data_dir: Path = PROJECT_ROOT / "data"
    seed: int = DEFAULT_SEED

    @field_validator("dataset_variant")
    @classmethod
    def _check_variant(cls, value: str) -> str:
        if value not in SUPPORTED_VARIANTS:
            raise ValueError(
                f"Unsupported dataset variant {value!r}. Choose one of {SUPPORTED_VARIANTS}."
            )
        return value

    @property
    def variant_slug(self) -> str:
        """Filesystem-safe form, e.g. 'hi_small'."""
        return self.dataset_variant.lower().replace("-", "_")

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        """Per-variant processed folder so Small and Medium outputs never collide."""
        return self.data_dir / "processed" / self.variant_slug

    @property
    def snapshots_dir(self) -> Path:
        return self.data_dir / "snapshots"


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
    return Settings(**values)
