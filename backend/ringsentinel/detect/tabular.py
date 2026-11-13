"""Per-transaction tabular features and the velocity rule (baselines, plan F4).

Everything here looks only at the transaction itself and at EARLIER transactions (velocity),
never at later ones, so it is safe for any split. No label or ring column is read.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TABULAR_COLUMNS = (
    "log_amount_inr",
    "payment_format_code",
    "hour_of_day",
    "is_self_transfer",
    "cross_bank",
    "cross_currency",
    "sender_cnt_24h",
    "receiver_cnt_24h",
)
VELOCITY_COLUMN = "sender_cnt_24h"
WINDOW_MINUTES = 24 * 60
REQUIRED_COLUMNS = (
    "ts", "src_account", "dst_account", "src_bank", "dst_bank",
    "amount_inr", "payment_format", "recv_currency", "pay_currency",
)  # fmt: skip


def trailing_counts(group: np.ndarray, minutes: np.ndarray, window: int = WINDOW_MINUTES):
    """For each row: how many rows of the same group have a time in [t - window, t).

    Strictly earlier minutes only, so the row itself and same-minute rows are excluded.
    Independent of row order.
    """
    group = np.asarray(group, dtype="int64")
    minutes = np.asarray(minutes, dtype="int64")
    if len(group) == 0:
        return np.zeros(0, dtype="int64")
    minutes = minutes - minutes.min()
    base = int(minutes.max()) + window + 2
    order = np.lexsort((minutes, group))
    composite = group[order] * base + minutes[order]
    upper = np.searchsorted(composite, composite, side="left")
    lower = np.searchsorted(composite, composite - window, side="left")
    counts = np.empty(len(group), dtype="int64")
    counts[order] = upper - lower
    return counts


def _codes(series: pd.Series) -> np.ndarray:
    """Integer code per row; equal codes mean equal values within this column."""
    if isinstance(series.dtype, pd.CategoricalDtype):
        return series.cat.codes.to_numpy().astype("int64")
    return pd.factorize(series.astype(str), sort=True)[0].astype("int64")


def _differs(a: pd.Series, b: pd.Series) -> np.ndarray:
    """Row-wise a != b as 0/1, comparing codes when both are categoricals with equal sets."""
    both_cat = isinstance(a.dtype, pd.CategoricalDtype) and isinstance(b.dtype, pd.CategoricalDtype)
    if both_cat and a.cat.categories.equals(b.cat.categories):
        return (a.cat.codes.to_numpy() != b.cat.codes.to_numpy()).astype("int64")
    return (a.astype(str).to_numpy() != b.astype(str).to_numpy()).astype("int64")


def tabular_frame(events: pd.DataFrame) -> np.ndarray:
    """float32 matrix (rows x len(TABULAR_COLUMNS)) in the order of TABULAR_COLUMNS."""
    missing = [c for c in REQUIRED_COLUMNS if c not in events.columns]
    if missing:
        raise ValueError(f"events is missing required columns: {missing}")
    ts = events["ts"].to_numpy("datetime64[ns]")
    minutes = ts.astype("datetime64[m]").astype("int64")
    src = _codes(events["src_account"])
    dst = _codes(events["dst_account"])
    fmt = events["payment_format"]
    if not isinstance(fmt.dtype, pd.CategoricalDtype):
        fmt = fmt.astype(str).astype("category")
    fmt_codes = fmt.cat.reorder_categories(sorted(fmt.cat.categories)).cat.codes
    out = np.column_stack(
        [
            np.log1p(events["amount_inr"].to_numpy("float64").clip(min=0)),
            fmt_codes.to_numpy(),
            (minutes // 60) % 24,
            1 - _differs(events["src_account"], events["dst_account"]),
            _differs(events["src_bank"], events["dst_bank"]),
            _differs(events["recv_currency"], events["pay_currency"]),
            trailing_counts(src, minutes),
            trailing_counts(dst, minutes),
        ]
    )  # fmt: skip
    return out.astype("float32")
