"""Per-transaction design matrices: tabular columns plus the graph features of both accounts.

Graph features are per (window, account) (data stage D6). A transaction in split S uses the
features of its sender and receiver from window S, so train rows see the train window, val rows
the val window and test rows the test window (all cumulative and past-only).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ringsentinel.detect.tabular import TABULAR_COLUMNS

NON_FEATURE_COLUMNS = ("window", "account", "community_id")


def graph_columns(features: pd.DataFrame) -> list[str]:
    return [c for c in features.columns if c not in NON_FEATURE_COLUMNS]


@dataclass
class WindowTable:
    """Graph features of one window: float32 values and the account -> row lookup."""

    accounts: pd.Index
    values: np.ndarray  # (n_accounts, n_graph_columns) float32

    def rows_for(self, categories: pd.Index) -> np.ndarray:
        """Row of each account category in this table, or -1 when the account is absent."""
        return self.accounts.get_indexer(categories)


def window_table(features: pd.DataFrame, window: str, columns: list[str]) -> WindowTable:
    part = features[features["window"].astype(str) == window]
    if part.empty:
        raise ValueError(f"No feature rows for window {window!r}.")
    accounts = pd.Index(part["account"].astype(str))
    if not accounts.is_unique:
        raise ValueError(f"Duplicate accounts in the {window!r} feature window.")
    return WindowTable(accounts=accounts, values=part[columns].to_numpy("float32"))


def feature_names(graph_cols: list[str], use_tabular: bool, use_graph: bool) -> list[str]:
    names: list[str] = list(TABULAR_COLUMNS) if use_tabular else []
    if use_graph:
        names += [f"src_{c}" for c in graph_cols] + [f"dst_{c}" for c in graph_cols]
    if not names:
        raise ValueError("A design matrix needs tabular and/or graph features.")
    return names


def design_matrix(
    rows: np.ndarray,
    tabular: np.ndarray,
    src_code: np.ndarray,
    dst_code: np.ndarray,
    table: WindowTable | None,
    cat_to_row: np.ndarray | None,
    *,
    use_tabular: bool,
    use_graph: bool,
) -> np.ndarray:
    """float32 matrix for the given row positions. Missing accounts give NaN graph values."""
    parts: list[np.ndarray] = []
    if use_tabular:
        parts.append(tabular[rows])
    if use_graph:
        if table is None or cat_to_row is None:
            raise ValueError("Graph features requested without a window table.")
        width = table.values.shape[1]
        for codes in (src_code[rows], dst_code[rows]):
            idx = cat_to_row[codes]
            block = np.full((len(rows), width), np.nan, dtype="float32")
            present = idx >= 0
            block[present] = table.values[idx[present]]
            parts.append(block)
    if not parts:
        raise ValueError("A design matrix needs tabular and/or graph features.")
    return np.concatenate(parts, axis=1) if len(parts) > 1 else parts[0]
