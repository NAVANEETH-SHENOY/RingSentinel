"""Elliptic settings: paths and the time-step split (environment names listed in .env.example).

Kept apart from `ringsentinel.config.Settings` so the Stage 01 to 07 settings object, its tests
and the saved `.env` files stay untouched. Seed, community cap and Louvain resolution are shared
with the core settings.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, model_validator

from ringsentinel.config import DEFAULT_HUB_CAP, Settings, get_settings

N_TIME_STEPS = 49  # Weber et al. 2019: 49 time steps (verify on the real file)
DEFAULT_TRAIN_LAST_STEP = 29
DEFAULT_VAL_LAST_STEP = 34  # steps 35..49 are the test period used in the literature


class EllipticSettings(BaseModel):
    core: Settings
    raw_dir: Path
    train_last_step: int = DEFAULT_TRAIN_LAST_STEP
    val_last_step: int = DEFAULT_VAL_LAST_STEP
    hub_cap: int = DEFAULT_HUB_CAP

    @model_validator(mode="after")
    def _check(self) -> EllipticSettings:
        if not 1 <= self.train_last_step < self.val_last_step < N_TIME_STEPS:
            raise ValueError(
                "Need 1 <= RS_ELLIPTIC_TRAIN_LAST_STEP < RS_ELLIPTIC_VAL_LAST_STEP < "
                f"{N_TIME_STEPS} so that train, validation and test are all non-empty."
            )
        if self.hub_cap < 2:
            raise ValueError("RS_ELLIPTIC_HUB_CAP must be at least 2.")
        return self

    # ---- raw files (data/raw/elliptic) ----
    @property
    def features_path(self) -> Path:
        return self.raw_dir / "elliptic_txs_features.csv"

    @property
    def classes_path(self) -> Path:
        return self.raw_dir / "elliptic_txs_classes.csv"

    @property
    def edgelist_path(self) -> Path:
        return self.raw_dir / "elliptic_txs_edgelist.csv"

    @property
    def manifest_path(self) -> Path:
        """The shared, committed data/raw/MANIFEST.json (Elliptic is one more entry in it)."""
        return self.core.manifest_path

    # ---- outputs (data/processed/elliptic) ----
    @property
    def out_dir(self) -> Path:
        return self.core.data_dir / "processed" / "elliptic"

    @property
    def metrics_path(self) -> Path:
        return self.out_dir / "metrics.json"

    @property
    def scores_path(self) -> Path:
        return self.out_dir / "scores.parquet"

    @property
    def results_path(self) -> Path:
        return self.out_dir / "results.md"

    @property
    def gnn_path(self) -> Path:
        return self.out_dir / "gnn.json"


def load_elliptic_settings(load_env_file: bool = True) -> EllipticSettings:
    core = get_settings(load_env_file=load_env_file)
    values: dict[str, object] = {"core": core}
    raw = os.environ.get("RS_ELLIPTIC_DIR", "").strip()
    values["raw_dir"] = Path(raw) if raw else core.data_dir / "raw" / "elliptic"
    for env_name, field in (
        ("RS_ELLIPTIC_TRAIN_LAST_STEP", "train_last_step"),
        ("RS_ELLIPTIC_VAL_LAST_STEP", "val_last_step"),
        ("RS_ELLIPTIC_HUB_CAP", "hub_cap"),
    ):
        text = os.environ.get(env_name, "").strip()
        if text:
            values[field] = int(text)
    if "hub_cap" not in values and core.hub_cap is not None:
        values["hub_cap"] = core.hub_cap
    return EllipticSettings(**values)
