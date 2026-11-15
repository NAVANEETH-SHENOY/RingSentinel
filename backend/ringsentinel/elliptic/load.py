"""Read the Elliptic files into one node table and an edge list (data stage D1 and D2).

Nothing here looks at labels except to copy them into the table; hub control, features and
splits are built elsewhere from the edge list and the time step only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ringsentinel.elliptic import schema as sc
from ringsentinel.elliptic.settings import N_TIME_STEPS, EllipticSettings


@dataclass
class EllipticData:
    tx_id: np.ndarray  # int64, one per node, sorted by (step, tx_id)
    step: np.ndarray  # int32, 1..49
    x: np.ndarray  # float32 (n, 165): 93 local then 72 aggregate features
    y: np.ndarray  # int8: 1 illicit, 0 licit, -1 unlabelled
    edge_src: np.ndarray  # int64 row positions into the node arrays
    edge_dst: np.ndarray
    report: dict

    @property
    def n(self) -> int:
        return len(self.tx_id)

    @property
    def local(self) -> np.ndarray:
        return self.x[:, : sc.N_LOCAL_FEATURES]


def _first_line(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig") as handle:
        return [c.strip().strip('"') for c in handle.readline().rstrip("\r\n").split(",")]


def _has_header(path: Path) -> bool:
    return not _first_line(path)[0].lstrip("-").isdigit()


def read_features(path: Path) -> pd.DataFrame:
    """Raw features table: column 0 txId, column 1 time step, columns 2.. features (float32)."""
    if not path.exists():
        raise FileNotFoundError(f"Missing {path.name} in {path.parent}")
    width = len(_first_line(path))
    if width != sc.N_FEATURE_COLUMNS:
        raise sc.EllipticSchemaError(
            f"{path.name}: expected {sc.N_FEATURE_COLUMNS} columns (txId, time step and "
            f"{sc.N_FEATURE_COLUMNS - 2} features), found {width}. VERIFY the download."
        )
    dtypes = {0: "int64", 1: "int64", **{i: "float32" for i in range(2, width)}}
    return pd.read_csv(path, header=0 if _has_header(path) else None, names=list(range(width)),
                       dtype=dtypes)  # fmt: skip


def read_classes(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing {path.name} in {path.parent}")
    frame = pd.read_csv(path, dtype={"txId": "int64", "class": "string"})
    if tuple(frame.columns) != sc.CLASS_COLUMNS:
        raise sc.EllipticSchemaError(
            f"{path.name}: expected columns {list(sc.CLASS_COLUMNS)}, found {list(frame.columns)}."
        )
    return frame


def read_edges(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing {path.name} in {path.parent}")
    frame = pd.read_csv(path, dtype="int64")
    if tuple(frame.columns) != sc.EDGE_COLUMNS:
        raise sc.EllipticSchemaError(
            f"{path.name}: expected columns {list(sc.EDGE_COLUMNS)}, found {list(frame.columns)}."
        )
    return frame


def assemble(features: pd.DataFrame, classes: pd.DataFrame, edges: pd.DataFrame) -> EllipticData:
    """Validate and join the three tables. Raises EllipticSchemaError on any inconsistency."""
    tx = features[0].to_numpy("int64")
    step = features[1].to_numpy("int64")
    if len(np.unique(tx)) != len(tx):
        raise sc.EllipticSchemaError("Duplicate txId in the features file.")
    if step.min() < 1 or step.max() > N_TIME_STEPS:
        raise sc.EllipticSchemaError(
            f"Time steps run {step.min()}..{step.max()}; expected within 1..{N_TIME_STEPS}."
        )
    unknown_class = set(classes["class"].dropna().unique()) - {
        sc.CLASS_ILLICIT, sc.CLASS_LICIT, sc.CLASS_UNKNOWN,
    }  # fmt: skip
    if unknown_class:
        raise sc.EllipticSchemaError(f"Unexpected class values: {sorted(unknown_class)}")
    if classes["txId"].duplicated().any():
        raise sc.EllipticSchemaError("Duplicate txId in the classes file.")

    order = np.lexsort((tx, step))
    tx, step = tx[order], step[order]
    x = features.iloc[order, 2:].to_numpy("float32")

    lookup = classes.set_index("txId")["class"]
    cls = lookup.reindex(tx)
    if cls.isna().any():
        raise sc.EllipticSchemaError(
            f"{int(cls.isna().sum())} transactions in the features file have no class row."
        )
    y = np.full(len(tx), sc.LABEL_UNKNOWN, dtype="int8")
    y[(cls == sc.CLASS_ILLICIT).to_numpy()] = 1
    y[(cls == sc.CLASS_LICIT).to_numpy()] = 0

    index = pd.Index(tx)
    src = index.get_indexer(edges["txId1"].to_numpy())
    dst = index.get_indexer(edges["txId2"].to_numpy())
    dangling = (src < 0) | (dst < 0)
    src, dst = src[~dangling], dst[~dangling]
    cross = int((step[src] != step[dst]).sum())

    report = {
        "nodes": int(len(tx)),
        "edges_in_file": int(len(edges)),
        "edges_kept": int(len(src)),
        "edges_dropped_unknown_endpoint": int(dangling.sum()),
        "edges_across_time_steps": cross,
        "illicit": int((y == 1).sum()),
        "licit": int((y == 0).sum()),
        "unlabelled": int((y == sc.LABEL_UNKNOWN).sum()),
        "time_steps": [int(step.min()), int(step.max())],
        "feature_columns": int(x.shape[1]),
        "nodes_without_any_edge": int(len(tx) - len(np.unique(np.r_[src, dst]))),
    }
    return EllipticData(tx, step.astype("int32"), x, y, src.astype("int64"),
                        dst.astype("int64"), report)  # fmt: skip


def load_elliptic(settings: EllipticSettings) -> EllipticData:
    return assemble(
        read_features(settings.features_path),
        read_classes(settings.classes_path),
        read_edges(settings.edgelist_path),
    )
