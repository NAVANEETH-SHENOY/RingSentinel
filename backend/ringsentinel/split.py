"""Temporal train / validation / test split (data stage D4).

Rows are split by timestamp, never at random:
    train: ts < val_start     val: val_start <= ts < test_start     test: ts >= test_start
so max(train ts) < min(val ts) < min(test ts). A ring belongs to the split of its earliest event.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

SPLIT_NAMES = ("train", "val", "test")


class SplitError(ValueError):
    """The split is empty, overlapping or badly configured."""


@dataclass(frozen=True)
class SplitCuts:
    val_start: pd.Timestamp
    test_start: pd.Timestamp

    def to_dict(self) -> dict:
        return {"val_start": str(self.val_start), "test_start": str(self.test_start)}


def compute_cuts(ts: pd.Series, train_frac: float, val_frac: float) -> SplitCuts:
    """Pick cut times so about train_frac / val_frac of rows fall before each cut."""
    if not (0 < train_frac < 1 and 0 < val_frac < 1 and train_frac + val_frac < 1):
        raise SplitError("Fractions must satisfy 0 < train, val and train + val < 1")
    values = np.sort(ts.to_numpy())
    n = len(values)
    if n < 10:
        raise SplitError("Too few events to split")
    val_start = pd.Timestamp(values[int(n * train_frac)])
    test_start = pd.Timestamp(values[int(n * (train_frac + val_frac))])
    if not val_start < test_start:
        raise SplitError("Validation window is empty: too many identical timestamps")
    return SplitCuts(val_start=val_start, test_start=test_start)


def assign_split(ts: pd.Series, cuts: SplitCuts) -> pd.Categorical:
    codes = (ts >= cuts.val_start).astype("int8") + (ts >= cuts.test_start).astype("int8")
    return pd.Categorical.from_codes(codes.to_numpy(), categories=list(SPLIT_NAMES))


def check_no_overlap(ts: pd.Series, split: pd.Categorical) -> None:
    labels = pd.Series(split, index=ts.index)
    bounds = {}
    for name in SPLIT_NAMES:
        part = ts[labels == name]
        if part.empty:
            raise SplitError(f"The {name} split is empty")
        bounds[name] = (part.min(), part.max())
    if not bounds["train"][1] < bounds["val"][0]:
        raise SplitError("train overlaps validation")
    if not bounds["val"][1] < bounds["test"][0]:
        raise SplitError("validation overlaps test")


def build_split(
    events: pd.DataFrame, rings: pd.DataFrame, train_frac: float, val_frac: float
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Return (split table, rings table with ring_split, metadata)."""
    cuts = compute_cuts(events["ts"], train_frac, val_frac)
    split = assign_split(events["ts"], cuts)
    check_no_overlap(events["ts"], split)
    split_table = pd.DataFrame({"event_id": events["event_id"].to_numpy(), "split": split})

    rings = rings.copy()
    rings["ring_split"] = (
        assign_split(rings["first_ts"], cuts) if len(rings) else pd.Categorical([])
    )

    illicit = events["is_illicit"].to_numpy() == 1
    meta = {
        "train_frac": train_frac,
        "val_frac": val_frac,
        "cuts": cuts.to_dict(),
        "rows": {n: int((split == n).sum()) for n in SPLIT_NAMES},
        "illicit_rows": {
            n: int(((split == n) & illicit).sum()) for n in SPLIT_NAMES
        },
        "rings_by_split": {n: int((rings["ring_split"] == n).sum()) for n in SPLIT_NAMES}
        if len(rings)
        else {n: 0 for n in SPLIT_NAMES},
        "note": "A ring belongs to the split of its earliest event; its rows keep their own "
        "time-based split.",
    }
    return split_table, rings, meta
