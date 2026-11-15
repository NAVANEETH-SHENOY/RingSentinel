"""Optional GraphSAGE detector (plan M8 stretch), written in plain PyTorch.

Deviation from the plan, flagged in docs/STAGE_08.md: the plan says "GraphSAGE ... if PyTorch
Geometric installs cleanly". A 2-layer mean-aggregator GraphSAGE needs only a sparse matrix
product, so this module uses PyTorch alone and avoids the extra, harder-to-install package.

Protocol (same as every other detector): the model is fitted on the train-window graph with the
train labels, early-stopped on validation average precision using the validation-window graph,
and scores the test rows once using the test-window graph. Node inputs are the 93 local features
only (standardised with train statistics), so any gain over `local_xgb` comes from message passing.

torch is NOT in requirements.txt. Install it with `pip install -r requirements-gnn.txt`. If it is
missing, `GnnUnavailableError` explains how, and nothing else in the project is affected.
"""

from __future__ import annotations

import importlib.util

import numpy as np

from ringsentinel.elliptic import graph as eg
from ringsentinel.elliptic.pipeline import Context, Predict
from ringsentinel.evaluate.metrics import average_precision
from ringsentinel.graph.build import WINDOW_SPLITS

HIDDEN = 64
MAX_EPOCHS = 200
PATIENCE = 30
LEARNING_RATE = 0.01
WEIGHT_DECAY = 1e-4
DROPOUT = 0.3


class GnnUnavailableError(RuntimeError):
    pass


def torch_available() -> bool:
    return importlib.util.find_spec("torch") is not None


def _require_torch():
    if not torch_available():
        raise GnnUnavailableError(
            "PyTorch is not installed. Run: pip install -r requirements-gnn.txt "
            "(optional; the rest of RingSentinel does not need it)."
        )
    import torch

    return torch


def mean_adjacency(n: int, src: np.ndarray, dst: np.ndarray):
    """Row-normalised undirected neighbour-mean operator as a torch sparse tensor.

    Duplicate and self edges are removed first. A node with no neighbours gets an all-zero row.
    """
    torch = _require_torch()
    a = np.concatenate([src, dst]).astype("int64")
    b = np.concatenate([dst, src]).astype("int64")
    keep = a != b
    a, b = a[keep], b[keep]
    key = np.unique(a * n + b)
    a, b = key // n, key % n
    degree = np.bincount(a, minlength=n).astype("float32")
    values = (1.0 / degree[a]).astype("float32")
    index = torch.from_numpy(np.vstack([a, b]))
    return torch.sparse_coo_tensor(
        index, torch.from_numpy(values), (n, n), check_invariants=True
    ).coalesce()


def _window_adjacency(ctx: Context) -> dict:
    d = ctx.data
    table = eg.edge_table(d, ctx.settings)
    split_of_edge = table["split"].to_numpy()
    out = {}
    for window, members in WINDOW_SPLITS.items():
        use = np.isin(split_of_edge, list(members))
        out[window] = mean_adjacency(d.n, d.edge_src[use], d.edge_dst[use])
    return out


def build_graphsage(ctx: Context) -> Predict:
    """Train GraphSAGE on train and validation rows and return a scoring function."""
    torch = _require_torch()
    nn = torch.nn
    seed = ctx.settings.core.seed
    torch.manual_seed(seed)
    torch.set_num_threads(1)
    d = ctx.data

    train_nodes = np.flatnonzero(ctx.codes == 0)
    mean = np.nanmean(d.local[train_nodes], axis=0)
    std = np.nanstd(d.local[train_nodes], axis=0)
    x = np.nan_to_num((d.local - mean) / np.where(std > 0, std, 1.0)).astype("float32")
    features = torch.from_numpy(x)
    adjacency = _window_adjacency(ctx)

    class SAGE(nn.Module):
        def __init__(self, width: int):
            super().__init__()
            self.l1 = nn.Linear(2 * width, HIDDEN)
            self.l2 = nn.Linear(2 * HIDDEN, HIDDEN)
            self.out = nn.Linear(HIDDEN, 1)
            self.drop = nn.Dropout(DROPOUT)

        def forward(self, h, adj):
            h = torch.relu(self.l1(torch.cat([h, torch.sparse.mm(adj, h)], dim=1)))
            h = self.drop(h)
            h = torch.relu(self.l2(torch.cat([h, torch.sparse.mm(adj, h)], dim=1)))
            return self.out(self.drop(h)).squeeze(1)

    model = SAGE(features.shape[1])
    optimiser = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
    tr, va = ctx.rows("train", True), ctx.rows("val", True)
    y_tr = torch.from_numpy(d.y[tr].astype("float32"))
    pos = float(y_tr.sum())
    if pos == 0 or pos == len(y_tr):
        raise ValueError("The train split needs both positive and negative labelled rows.")
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=torch.tensor((len(y_tr) - pos) / pos))

    best_ap, best_state, since = -1.0, None, 0
    for _ in range(MAX_EPOCHS):
        model.train()
        optimiser.zero_grad()
        loss = loss_fn(model(features, adjacency["train"])[torch.from_numpy(tr)], y_tr)
        loss.backward()
        optimiser.step()
        model.eval()
        with torch.no_grad():
            val_scores = torch.sigmoid(model(features, adjacency["val"]))[torch.from_numpy(va)]
        ap = average_precision(d.y[va], val_scores.numpy().astype("float64"))
        if ap > best_ap:
            best_ap, since = ap, 0
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        else:
            since += 1
            if since >= PATIENCE:
                break
    model.load_state_dict(best_state)
    model.eval()
    cache: dict[str, np.ndarray] = {}

    def predict(rows: np.ndarray, split: str) -> np.ndarray:
        if split not in cache:
            with torch.no_grad():
                cache[split] = torch.sigmoid(model(features, adjacency[split])).numpy()
        return cache[split][rows].astype("float32")

    return predict
