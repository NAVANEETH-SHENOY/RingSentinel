"""Model fitting for the detectors. The fit functions have no test-split parameter by design.

XGBoost uses one thread and a fixed seed (the same reproducibility rule as Stage 01).
Training keeps every positive row and a seeded share of the negative rows (`neg_sample_frac`);
scoring always covers every row of the split.
"""

from __future__ import annotations

import numpy as np
from sklearn.ensemble import IsolationForest
from xgboost import XGBClassifier

XGB_PARAMS = {
    "n_estimators": 400,
    "learning_rate": 0.08,
    "max_depth": 6,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 1,
    "tree_method": "hist",
    "eval_metric": "aucpr",
    "early_stopping_rounds": 40,
    "n_jobs": 1,
    "verbosity": 0,
}
IFOREST_PARAMS = {"n_estimators": 200, "max_samples": 256, "contamination": "auto", "n_jobs": 1}
IFOREST_TRAIN_ROWS = 200_000
SCORE_CHUNK = 250_000


def sample_rows(y: np.ndarray, neg_frac: float, seed: int) -> np.ndarray:
    """Sorted indices: every positive plus a seeded `neg_frac` share of the negatives."""
    y = np.asarray(y)
    rng = np.random.default_rng(seed)
    positives = np.flatnonzero(y == 1)
    negatives = np.flatnonzero(y == 0)
    if neg_frac < 1.0:
        keep = int(round(len(negatives) * neg_frac))
        negatives = np.sort(rng.choice(negatives, size=keep, replace=False))
    return np.sort(np.concatenate([positives, negatives]))


def fit_xgb(
    x_train: np.ndarray, y_train: np.ndarray, x_val: np.ndarray, y_val: np.ndarray, seed: int
) -> XGBClassifier:
    """Fit on train, stop early on validation. Raises if either split lacks a class."""
    for name, y in (("train", y_train), ("validation", y_val)):
        if int(np.sum(y == 1)) == 0 or int(np.sum(y == 0)) == 0:
            raise ValueError(f"The {name} split needs both positive and negative rows.")
    model = XGBClassifier(**XGB_PARAMS, random_state=seed)
    model.fit(x_train, y_train, eval_set=[(x_val, y_val)], verbose=False)
    return model


def score_chunks(predict, make_chunk, n_rows: int, chunk: int = SCORE_CHUNK) -> np.ndarray:
    """Score n_rows in chunks so the design matrix never has to exist all at once."""
    out = np.empty(n_rows, dtype="float32")
    for start in range(0, n_rows, chunk):
        stop = min(start + chunk, n_rows)
        out[start:stop] = predict(make_chunk(start, stop))
    return out


def xgb_predict(model: XGBClassifier):
    return lambda x: model.predict_proba(x)[:, 1]


class ImputedIsolationForest:
    """Isolation Forest on median-imputed features. Unsupervised: labels are never used."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.medians: np.ndarray | None = None
        self.model: IsolationForest | None = None

    def fit(self, x_train: np.ndarray) -> ImputedIsolationForest:
        with np.errstate(all="ignore"):
            medians = np.nanmedian(x_train, axis=0)
        self.medians = np.where(np.isnan(medians), 0.0, medians).astype("float32")
        self.model = IsolationForest(**IFOREST_PARAMS, random_state=self.seed)
        self.model.fit(self._impute(x_train))
        return self

    def _impute(self, x: np.ndarray) -> np.ndarray:
        x = np.array(x, dtype="float32", copy=True)
        nan = np.isnan(x)
        if nan.any():
            x[nan] = np.broadcast_to(self.medians, x.shape)[nan]
        return x

    def predict(self, x: np.ndarray) -> np.ndarray:
        """Anomaly score: higher means more unusual."""
        return (-self.model.score_samples(self._impute(x))).astype("float32")
