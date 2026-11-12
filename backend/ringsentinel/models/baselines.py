"""Baseline detectors that every later detector is compared against (feature F4).

1. Velocity rule: how many transfers an account sent or received in the previous 24 hours.
2. Tabular XGBoost: row-level features only (amount, currency, payment format, time of day).

Both use only information available at the time of the transaction.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from xgboost import XGBClassifier

VELOCITY_WINDOW_SECONDS = 24 * 3600

TABULAR_FEATURES = [
    "log_amount_inr",
    "log_amount_paid",
    "log_amount_received",
    "same_account",
    "same_bank",
    "cross_currency",
    "hour",
    "recv_currency_code",
    "pay_currency_code",
    "payment_format_code",
]

XGB_PARAMS = {
    "n_estimators": 300,
    "max_depth": 6,
    "learning_rate": 0.1,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "tree_method": "hist",
    "eval_metric": "aucpr",
    "early_stopping_rounds": 30,
}


def trailing_counts(group_codes: np.ndarray, ts_seconds: np.ndarray, window: int) -> np.ndarray:
    """For each event, count events of the same group with time in (t - window, t].

    Events at the same instant count each other; nothing after the instant is counted.
    """
    g = np.asarray(group_codes).astype("int64")
    t = np.asarray(ts_seconds).astype("int64")
    t = t - t.min()
    order = np.lexsort((t, g))
    g_sorted, t_sorted = g[order], t[order]
    span = int(t_sorted.max()) + window + 1  # larger than any in-group time plus the window
    keys = g_sorted * span + t_sorted
    left = np.searchsorted(keys, keys - window, side="right")
    right = np.searchsorted(keys, keys, side="right")
    counts = np.empty(len(keys), dtype="int64")
    counts[order] = right - left
    return counts


def _seconds(ts: pd.Series) -> np.ndarray:
    return (ts - ts.min()).dt.total_seconds().to_numpy().astype("int64")


def velocity_scores(events: pd.DataFrame) -> np.ndarray:
    """Velocity rule score: the larger of sender's outgoing and receiver's incoming 24h counts."""
    seconds = _seconds(events["ts"])
    out_count = trailing_counts(
        events["src_account"].cat.codes.to_numpy(), seconds, VELOCITY_WINDOW_SECONDS
    )
    in_count = trailing_counts(
        events["dst_account"].cat.codes.to_numpy(), seconds, VELOCITY_WINDOW_SECONDS
    )
    return np.maximum(out_count, in_count).astype("float64")


def tabular_features(events: pd.DataFrame) -> pd.DataFrame:
    """Row-level features. Currency and format codes are positions in the sorted category list."""
    return pd.DataFrame(
        {
            "log_amount_inr": np.log1p(events["amount_inr"].to_numpy()).astype("float32"),
            "log_amount_paid": np.log1p(events["amount_paid"].to_numpy()).astype("float32"),
            "log_amount_received": np.log1p(events["amount_received"].to_numpy()).astype("float32"),
            "same_account": (events["src_account"] == events["dst_account"]).astype("int8"),
            "same_bank": (events["src_bank"] == events["dst_bank"]).astype("int8"),
            "cross_currency": (events["recv_currency"] != events["pay_currency"]).astype("int8"),
            "hour": events["ts"].dt.hour.astype("int8"),
            "recv_currency_code": events["recv_currency"].cat.codes.astype("int16"),
            "pay_currency_code": events["pay_currency"].cat.codes.astype("int16"),
            "payment_format_code": events["payment_format"].cat.codes.astype("int16"),
        },
        index=events.index,
    )[TABULAR_FEATURES]


def train_xgb(
    x_train: pd.DataFrame,
    y_train: np.ndarray,
    x_val: pd.DataFrame,
    y_val: np.ndarray,
    seed: int,
    n_jobs: int = 1,
) -> XGBClassifier:
    """Fit on train; early stopping watches validation PR-AUC. The test split is never passed."""
    positives = int(np.sum(y_train))
    if positives == 0:
        raise ValueError("No positive examples in the training split")
    negatives = len(y_train) - positives
    model = XGBClassifier(
        **XGB_PARAMS,
        scale_pos_weight=negatives / positives,
        random_state=seed,
        n_jobs=n_jobs,
    )
    model.fit(x_train, y_train, eval_set=[(x_val, y_val)], verbose=False)
    return model
