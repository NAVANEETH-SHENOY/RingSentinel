"""Run every Elliptic detector under the Stage 03 protocol and write metrics (data stage D9).

Protocol, identical in spirit to docs/EVALUATION.md:
  * split by time step (train / validation / test), never at random;
  * models are fitted on train and stopped early on validation, through `SplitVault.fit_view()`;
  * the F1 threshold is chosen on validation only, then the test steps are scored ONCE per
    detector through `SplitVault.release_test()` and judged at that fixed threshold;
  * metrics come from the shared Stage 03 functions (`average_precision`,
    `best_f1_threshold`, `precision_recall_f1`).

Only labelled transactions are fitted and judged. Every transaction of the validation and test
steps is scored (labels are not needed to score), and those scores feed the label-free drift
monitor (PSI of each test step against the validation scores).
"""

from __future__ import annotations

import json
import platform
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
import xgboost

from ringsentinel.detect.guard import SplitVault
from ringsentinel.detect.models import ImputedIsolationForest, fit_xgb, xgb_predict
from ringsentinel.elliptic import graph as eg
from ringsentinel.elliptic import schema as sc
from ringsentinel.elliptic.load import EllipticData, load_elliptic
from ringsentinel.elliptic.settings import EllipticSettings
from ringsentinel.elliptic.split import split_codes, split_nodes
from ringsentinel.evaluate.metrics import average_precision, best_f1_threshold, precision_recall_f1
from ringsentinel.monitor.drift import classify, psi

DETECTORS = ("degree_rule", "local_iforest", "local_xgb", "all_xgb", "graph_xgb")
ABLATIONS = ("graph_xgb_nohub",)
LABELS = {
    "degree_rule": "Degree rule (sanity floor)",
    "local_iforest": "Isolation Forest, local features",
    "local_xgb": "XGBoost, local features (tabular baseline)",
    "all_xgb": "XGBoost, local + provider aggregates",
    "graph_xgb": "XGBoost, local + RingSentinel graph features",
    "graph_xgb_nohub": "XGBoost, local + graph features, no hub cap",
    "graphsage": "GraphSAGE (optional, plain PyTorch)",
}
SPLIT_INDEX = {"train": 0, "val": 1, "test": 2}
PSI_BINS = 10

Predict = Callable[[np.ndarray, str], np.ndarray]  # (node rows, split name) -> scores


class Context:
    """Everything the detectors need, computed once."""

    def __init__(self, data: EllipticData, settings: EllipticSettings):
        self.data, self.settings = data, settings
        self.codes = split_codes(split_nodes(data.step, settings))
        self.labelled = data.y >= 0
        self.frames = eg.window_frames(data, settings, settings.hub_cap)
        self._nohub: dict[str, pd.DataFrame] | None = None

    @property
    def frames_nohub(self) -> dict[str, pd.DataFrame]:
        if self._nohub is None:
            self._nohub = eg.window_frames(self.data, self.settings, eg.NO_HUB_CAP)
        return self._nohub

    def rows(self, split: str, labelled_only: bool) -> np.ndarray:
        mask = self.codes == SPLIT_INDEX[split]
        if labelled_only:
            mask &= self.labelled
        return np.flatnonzero(mask)

    def matrix(self, kind: str, rows: np.ndarray, split: str) -> np.ndarray:
        d = self.data
        if kind == "local":
            return d.local[rows]
        if kind == "all":
            return d.x[rows]
        frames = self.frames_nohub if kind == "graph_nohub" else self.frames
        return np.hstack([d.local[rows], eg.graph_matrix(d, rows, frames[split])])


def _fit_xgb(ctx: Context, kind: str, seed: int) -> Predict:
    tr, va = ctx.rows("train", True), ctx.rows("val", True)
    model = fit_xgb(
        ctx.matrix(kind, tr, "train"), ctx.data.y[tr],
        ctx.matrix(kind, va, "val"), ctx.data.y[va], seed,
    )  # fmt: skip
    predict = xgb_predict(model)
    return lambda rows, split: predict(ctx.matrix(kind, rows, split))


def _fit_iforest(ctx: Context, seed: int) -> Predict:
    tr = ctx.rows("train", True)
    model = ImputedIsolationForest(seed).fit(ctx.matrix("local", tr, "train"))
    return lambda rows, split: model.predict(ctx.matrix("local", rows, split))


def _degree_rule(ctx: Context) -> Predict:
    def predict(rows: np.ndarray, split: str) -> np.ndarray:
        col = eg.GRAPH_COLUMNS.index("degree")
        values = eg.graph_matrix(ctx.data, rows, ctx.frames[split])[:, col]
        return np.nan_to_num(values, nan=0.0).astype("float32")

    return predict


def fit_detector(name: str, ctx: Context) -> Predict:
    """Build a scoring function. Fit functions see only train and validation rows."""
    seed = ctx.settings.core.seed
    if name == "degree_rule":
        return _degree_rule(ctx)
    if name == "local_iforest":
        return _fit_iforest(ctx, seed)
    kinds = {"local_xgb": "local", "all_xgb": "all", "graph_xgb": "graph",
             "graph_xgb_nohub": "graph_nohub"}  # fmt: skip
    if name not in kinds:
        raise ValueError(f"Unknown detector {name!r}.")
    return _fit_xgb(ctx, kinds[name], seed)


def _score_all(ctx: Context, predict: Predict, split: str) -> tuple[np.ndarray, np.ndarray]:
    rows = ctx.rows(split, labelled_only=False)
    return rows, np.asarray(predict(rows, split), dtype="float64")


def _step_blocks(
    ctx: Context, rows: np.ndarray, scores: np.ndarray, ref_scores: np.ndarray, theta: float
) -> list[dict]:
    """Per test time step: judgement on labelled rows at the fixed threshold, plus PSI."""
    s = ctx.settings.core
    out = []
    steps = ctx.data.step[rows]
    for step in np.unique(steps):
        here = steps == step
        lab = here & ctx.labelled[rows]
        y, sc_ = ctx.data.y[rows][lab], scores[lab]
        block = precision_recall_f1(y, sc_ >= theta) if lab.any() else {}
        n_all = int(here.sum())
        value = psi(ref_scores, scores[here], PSI_BINS) if n_all >= s.drift_min_events else None
        out.append(
            {
                "step": int(step), "nodes": n_all, "labelled": int(lab.sum()),
                "positives": int(y.sum()) if lab.any() else 0,
                "precision": block.get("precision"), "recall": block.get("recall"),
                "f1": block.get("f1"),
                "pr_auc": average_precision(y, sc_) if lab.any() and y.sum() > 0 else None,
                "psi": value, "psi_status": classify(value, s.psi_warn_level, s.psi_alert_level),
            }
        )  # fmt: skip
    return out


def evaluate_detector(
    ctx: Context, vault: SplitVault, name: str, predict: Predict
) -> tuple[dict, dict[str, np.ndarray]]:
    """Report for one detector, and its scores per split (all nodes of val and test)."""
    fit = vault.fit_view()
    val_rows_all, val_scores_all = _score_all(ctx, predict, "val")
    val_lab = ctx.labelled[val_rows_all]
    yv, sv = ctx.data.y[val_rows_all][val_lab], val_scores_all[val_lab]
    choice = best_f1_threshold(yv, sv)
    theta = choice["threshold"]

    test_rows_all = vault.release_test(name)
    test_scores_all = np.asarray(predict(test_rows_all, "test"), dtype="float64")
    test_lab = ctx.labelled[test_rows_all]
    yt, st = ctx.data.y[test_rows_all][test_lab], test_scores_all[test_lab]

    at_theta = precision_recall_f1(yt, st >= theta)
    at_theta["threshold"] = theta
    report = {
        "label": LABELS.get(name, name),
        "val": {
            "pr_auc": average_precision(yv, sv), "positives": int(yv.sum()),
            "prevalence": float(yv.mean()),
            "note": "Optimistic: the threshold and early stopping were chosen on this split.",
        },
        "test": {
            "pr_auc": average_precision(yt, st), "positives": int(yt.sum()),
            "prevalence": float(yt.mean()), "labelled": int(len(yt)),
            "at_f1_threshold": at_theta,
        },
        "threshold": {"f1": theta, "chosen_on": "validation", "val_f1": choice["f1"]},
        "per_step": _step_blocks(ctx, test_rows_all, test_scores_all, val_scores_all, theta),
        "fit_splits": sorted(fit),
    }
    return report, {"val": (val_rows_all, val_scores_all), "test": (test_rows_all, test_scores_all)}


def _meta(ctx: Context) -> dict:
    s, d = ctx.settings, ctx.data
    per = {}
    for split in SPLIT_INDEX:
        lab = ctx.rows(split, True)
        per[split] = {
            "steps": [int(d.step[ctx.codes == SPLIT_INDEX[split]].min()),
                      int(d.step[ctx.codes == SPLIT_INDEX[split]].max())],
            "nodes": int((ctx.codes == SPLIT_INDEX[split]).sum()),
            "labelled": int(len(lab)),
            "illicit": int(d.y[lab].sum()),
            "illicit_share_of_labelled": float(d.y[lab].mean()) if len(lab) else None,
        }  # fmt: skip
    return {
        "dataset": "Elliptic Data Set (Weber et al., 2019); transaction-level",
        "graph": d.report, "splits": per, "seed": s.core.seed, "hub_cap": s.hub_cap,
        "hub_cap_note": "Untuned default: Elliptic has no ring labels to tune it on.",
        "graph_columns": list(eg.GRAPH_COLUMNS),
        "graph_columns_excluded": list(eg.EXCLUDED_COLUMNS),
        "local_features": sc.N_LOCAL_FEATURES, "aggregate_features": sc.N_AGGREGATE_FEATURES,
        "psi": {"bins": PSI_BINS, "warn": s.core.psi_warn_level, "alert": s.core.psi_alert_level,
                "min_nodes": s.core.drift_min_events, "reference": "validation-step scores"},
        "not_applicable": [
            "ring-level precision and recall (no ring labels)",
            "rupee cost model and net value (no amounts)",
            "velocity rule (no clock time within a step)",
        ],
        "versions": {"python": platform.python_version(), "numpy": np.__version__,
                     "pandas": pd.__version__, "scikit-learn": sklearn.__version__,
                     "xgboost": xgboost.__version__},
    }  # fmt: skip


def run_elliptic(
    settings: EllipticSettings, data: EllipticData | None = None, *,
    with_ablation: bool = True, extra: dict[str, Callable[[Context], Predict]] | None = None,
    write: bool = True,
) -> dict:  # fmt: skip
    """Fit and judge every detector; write metrics.json, scores.parquet and results.md.

    `extra` lets the optional GraphSAGE run (see gnn.py) join the same protocol: each entry maps
    a detector name to a function that receives the Context and returns a scoring function.
    """
    data = data or load_elliptic(settings)
    ctx = Context(data, settings)
    vault = SplitVault(
        {"train": ctx.rows("train", True), "val": ctx.rows("val", True)},
        lambda: ctx.rows("test", labelled_only=False),
    )
    detectors: dict[str, dict] = {}
    score_cols: dict[str, np.ndarray] = {}
    names = list(DETECTORS) + (list(ABLATIONS) if with_ablation else [])
    builders: dict[str, Callable[[], Predict]] = {
        n: (lambda n=n: fit_detector(n, ctx)) for n in names
    }
    for name, make in (extra or {}).items():
        builders[name] = lambda make=make: make(ctx)
    for name, build in builders.items():
        report, scored = evaluate_detector(ctx, vault, name, build())
        report["role"] = "ablation" if name in ABLATIONS else "detector"
        detectors[name] = report
        col = np.full(data.n, np.nan, dtype="float32")
        for rows, scores in scored.values():
            col[rows] = scores
        score_cols[name] = col
    metrics = {"meta": _meta(ctx), "detectors": detectors,
               "test_released_for": sorted(vault.released)}  # fmt: skip
    if write:
        settings.out_dir.mkdir(parents=True, exist_ok=True)
        _write_json(settings.metrics_path, metrics)
        table = pd.DataFrame({"tx_id": data.tx_id, "step": data.step,
                              "split": np.array(["train", "val", "test"])[ctx.codes],
                              "label": data.y, **score_cols})  # fmt: skip
        table.to_parquet(settings.scores_path, index=False)
        settings.results_path.write_text(format_results(metrics), encoding="utf-8")
    return metrics


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fmt(value, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def format_results(metrics: dict) -> str:
    """Markdown for the Elliptic results (generated from metrics.json only)."""
    meta = metrics["meta"]
    split = meta["splits"]
    out = [
        "# Elliptic results (generated)",
        "",
        "Generated by `scripts/run_stage08.py`. Do not edit by hand. Transaction-level only: "
        "no ring, rupee or velocity results exist for this dataset.",
        "",
        f"Time steps: train {split['train']['steps']}, validation {split['val']['steps']}, "
        f"test {split['test']['steps']}. Seed {meta['seed']}; hub cap {meta['hub_cap']} (untuned).",
        "",
        "| Detector | Val PR-AUC | Test PR-AUC | Test P | Test R | Test F1 | Role |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, d in metrics["detectors"].items():
        t = d["test"]["at_f1_threshold"]
        out.append(
            f"| {name} | {_fmt(d['val']['pr_auc'])} | {_fmt(d['test']['pr_auc'])} | "
            f"{_fmt(t['precision'])} | {_fmt(t['recall'])} | {_fmt(t['f1'])} | {d['role']} |"
        )
    out += [
        "",
        "Test P, R, F1 are for the illicit class at the F1 threshold chosen on validation. "
        "Validation PR-AUC is optimistic.",
        "",
        "## Per test time step (graph_xgb)",
        "",
        "| Step | Labelled | Illicit | F1 | PSI vs validation | PSI status |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in metrics["detectors"].get("graph_xgb", {}).get("per_step", []):
        out.append(
            f"| {r['step']} | {r['labelled']} | {r['positives']} | {_fmt(r['f1'])} | "
            f"{_fmt(r['psi'])} | {r['psi_status']} |"
        )
    return "\n".join(out) + "\n"


# Cross-dataset table (plan M8 done-when: a second dataset column) --------------------------
ROLES = (
    ("Velocity rule", "velocity", None),
    ("Unsupervised (Isolation Forest)", "iforest", "local_iforest"),
    ("Tabular XGBoost", "xgb_tabular", "local_xgb"),
    ("Graph-feature XGBoost (RingSentinel)", "xgb_graph", "graph_xgb"),
)


def cross_dataset_table(ibm: dict | None, elliptic: dict | None) -> str:
    """Rows are detector roles; columns are the two datasets. Missing results say so."""
    def cells(source: dict | None, key: str | None) -> tuple[str, str]:
        if key is None:
            return "n/a (no clock time)", "n/a"
        if not source or key not in source.get("detectors", {}):
            return "not run", "not run"
        t = source["detectors"][key]["test"]
        return _fmt(t["pr_auc"]), _fmt(t["at_f1_threshold"]["f1"])

    lines = [
        "# Results table, two datasets (generated)",
        "",
        "Generated by `scripts/run_stage08.py table`. IBM AML HI-Small is transfer-level on "
        "accounts; Elliptic is transaction-level on Bitcoin transactions. Columns are NOT "
        "comparable in difficulty or prevalence: read each dataset against its own baselines.",
        "",
        "| Detector role | IBM AML test PR-AUC | IBM AML test F1 | Elliptic test PR-AUC | "
        "Elliptic test F1 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for label, ibm_key, ell_key in ROLES:
        ibm_cells = cells(ibm, ibm_key)
        ell_cells = cells(elliptic, ell_key) if ell_key else ("n/a (no clock time)", "n/a")
        lines.append(f"| {label} | {ibm_cells[0]} | {ibm_cells[1]} | {ell_cells[0]} | "
                     f"{ell_cells[1]} |")  # fmt: skip
    lines += [
        "",
        "Ring-level precision and recall and the rupee net value exist for IBM AML only.",
    ]
    return "\n".join(lines) + "\n"
