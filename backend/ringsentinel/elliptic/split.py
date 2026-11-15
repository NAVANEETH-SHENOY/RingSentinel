"""Temporal split by time step (data stage D4 for Elliptic).

Train: steps 1..train_last. Validation: train_last+1..val_last. Test: val_last+1..49. Steps are
cut at whole-step boundaries, so no step is shared between two splits. The shared Stage 01
`check_no_overlap` is run on a pseudo clock (step number to a date) as the same guard.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ringsentinel.elliptic.settings import EllipticSettings
from ringsentinel.split import SPLIT_NAMES, check_no_overlap

CLOCK_START = pd.Timestamp("2019-01-01")
STEP_LENGTH = pd.Timedelta(days=14)  # pseudo clock: only the ORDER of steps is real


def step_to_ts(step: np.ndarray) -> pd.Series:
    """Pseudo timestamp per time step. The real dates are not part of the data set."""
    return pd.Series(CLOCK_START + (np.asarray(step, dtype="int64") - 1) * STEP_LENGTH)


def assign(step: np.ndarray, train_last: int, val_last: int) -> pd.Categorical:
    step = np.asarray(step)
    codes = (step > train_last).astype("int8") + (step > val_last).astype("int8")
    return pd.Categorical.from_codes(codes, categories=list(SPLIT_NAMES))


def split_nodes(step: np.ndarray, settings: EllipticSettings) -> pd.Categorical:
    split = assign(step, settings.train_last_step, settings.val_last_step)
    check_no_overlap(step_to_ts(step), split)
    return split


def split_codes(split: pd.Categorical) -> np.ndarray:
    return np.asarray(split.codes, dtype="int8")
