"""Stage 03 orchestration: detectors (D7), ring extraction and evaluation (D8, D9).

Steps (each reads files written by the earlier ones):
    run_detect      fit and score the four detectors            -> scores.parquet, models/
    run_evaluate    thresholds, rings, metrics, cost, latency   -> metrics.json, rings.json, ...
    run_ablate      hub control on/off, graph features on/off   -> ablations.json
    run_robustness  edge dropout on the test-window graph       -> robustness.json

Protocol: fit on train, early-stop and choose every threshold on validation, score the test
split once per detector. See docs/EVALUATION.md.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass

import joblib
import numpy as np
import pandas as pd
from xgboost import DMatrix, XGBClassifier

from ringsentinel.config import Settings
from ringsentinel.detect.guard import SplitVault
from ringsentinel.detect.matrix import (
    WindowTable,
    design_matrix,
    feature_names,
    graph_columns,
    window_table,
)
from ringsentinel.detect.models import (
    IFOREST_TRAIN_ROWS,
    ImputedIsolationForest,
    fit_xgb,
    sample_rows,
    score_chunks,
    xgb_predict,
)
from ringsentinel.detect.tabular import TABULAR_COLUMNS, VELOCITY_COLUMN, tabular_frame
from ringsentinel.evaluate.cost import CostParams
from ringsentinel.evaluate.metrics import average_precision, precision_recall_f1
from ringsentinel.evaluate.report import (
    ExtractionSettings,
    Scored,
    SplitCtx,
    cost_sweep,
    evaluate_detector,
    latency_block,
    ring_block,
)
from ringsentinel.features.build import REQUIRED_COLUMNS as GRAPH_EVENT_COLUMNS
from ringsentinel.features.build import build_window_features
from ringsentinel.features.community import attach_to_nodes, community_features
from ringsentinel.features.node import node_features
from ringsentinel.graph.build import WINDOW_SPLITS, build_graph, cumulative_events
from ringsentinel.graph.communities import detect_communities
from ringsentinel.graph.hubs import effective_hub_cap

SPLITS = ("train", "val", "test")
DETECTORS = ("velocity", "xgb_tabular", "xgb_graph", "iforest")
ABLATION_DETECTORS = ("xgb_tabular", "xgb_graph_nohub", "xgb_graph")
VARIANTS = {"tabular": (True, False), "graph": (True, True)}
ROBUSTNESS_LEVELS = (0.0, 0.1, 0.2, 0.3, 0.5)
EVENT_COLUMNS = [
    "event_id", "ts", "src_account", "dst_account", "src_bank", "dst_bank", "amount_inr",
    "payment_format", "recv_currency", "pay_currency", "is_illicit", "ring_id",
]  # fmt: skip


def _write_json(path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")


def _json_default(value):
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"Cannot serialise {type(value)}")


def _clean(obj):
    """Replace non-finite floats (JSON has no inf) by the strings 'inf' / '-inf'."""
    if isinstance(obj, float) and not np.isfinite(obj):
        return "inf" if obj > 0 else "-inf"
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


def write_report(path, payload) -> None:
    _write_json(path, _clean(payload))


# ------------------------------------------------------------------ data
@dataclass
class Prepared:
    """Events as aligned numpy arrays (Stage 01 order: sorted by time)."""

    event_id: np.ndarray
    minutes: np.ndarray
    amount_inr: np.ndarray
    y: np.ndarray
    ring_id: np.ndarray  # -1 when in no pattern ring
    src: np.ndarray
    dst: np.ndarray
    categories: pd.Index
    split_code: np.ndarray
    tab: np.ndarray
    ring_split: dict[int, str]

    @property
    def n(self) -> int:
        return len(self.y)

    def rows(self, split: str) -> np.ndarray:
        return np.flatnonzero(self.split_code == SPLITS.index(split))


@dataclass
class FeatureTables:
    """Graph-feature tables per window plus the account-category lookup for each."""

    tables: dict[str, WindowTable]
    cat_to_row: dict[str, np.ndarray]
    columns: list[str]


def account_codes(events: pd.DataFrame) -> tuple[pd.Index, np.ndarray, np.ndarray]:
    src, dst = events["src_account"], events["dst_account"]
    cat = pd.CategoricalDtype
    if isinstance(src.dtype, cat) and isinstance(dst.dtype, cat):
        if src.cat.categories.equals(dst.cat.categories):
            return (
                pd.Index(src.cat.categories.astype(str)),
                src.cat.codes.to_numpy().astype("int64"),
                dst.cat.codes.to_numpy().astype("int64"),
            )
    both = pd.concat([src.astype(str), dst.astype(str)], ignore_index=True)
    codes, uniques = pd.factorize(both, sort=True)
    m = len(src)
    return pd.Index(uniques), codes[:m].astype("int64"), codes[m:].astype("int64")


def load_prepared(settings: Settings) -> Prepared:
    events = pd.read_parquet(settings.events_path, columns=EVENT_COLUMNS)
    split = pd.read_parquet(settings.split_path)
    events = events.merge(split, on="event_id", how="left", validate="one_to_one")
    if events["split"].isna().any():
        raise ValueError("Some events have no split. Rerun Stage 01 (split step).")
    categories, src, dst = account_codes(events)
    split_code = np.full(len(events), -1, dtype="int8")
    for i, name in enumerate(SPLITS):
        split_code[(events["split"] == name).to_numpy()] = i
    ring_id = events["ring_id"].astype("float64").fillna(-1).to_numpy().astype("int64")
    rings = pd.read_parquet(settings.rings_truth_path, columns=["ring_id", "ring_split"])
    ring_split = {
        int(r): str(s) for r, s in zip(rings["ring_id"], rings["ring_split"], strict=True)
    }
    return Prepared(
        event_id=events["event_id"].to_numpy("int64"),
        minutes=events["ts"].to_numpy("datetime64[ns]").astype("datetime64[m]").astype("int64"),
        amount_inr=events["amount_inr"].to_numpy("float64"),
        y=events["is_illicit"].to_numpy("int8"),
        ring_id=ring_id, src=src, dst=dst, categories=categories, split_code=split_code,
        tab=tabular_frame(events), ring_split=ring_split,
    )  # fmt: skip


def load_tables(prep: Prepared, features: pd.DataFrame, columns: list[str] | None = None):
    columns = columns or graph_columns(features)
    tables = {w: window_table(features, w, columns) for w in WINDOW_SPLITS}
    cat_to_row = {w: t.rows_for(prep.categories) for w, t in tables.items()}
    return FeatureTables(tables=tables, cat_to_row=cat_to_row, columns=columns)


def matrix_for(prep, tables, rows, window, variant) -> np.ndarray:
    use_tab, use_graph = VARIANTS[variant]
    return design_matrix(
        rows, prep.tab, prep.src, prep.dst,
        tables.tables[window] if use_graph else None,
        tables.cat_to_row[window] if use_graph else None,
        use_tabular=use_tab, use_graph=use_graph,
    )  # fmt: skip


def split_ctx(prep: Prepared, split: str) -> SplitCtx:
    rows = prep.rows(split)
    truth_ids = {r for r, s in prep.ring_split.items() if s == split}
    in_truth = np.isin(prep.ring_id, list(truth_ids)) if truth_ids else np.zeros(prep.n, bool)
    pairs = pd.concat(
        [
            pd.DataFrame({"r": prep.ring_id[in_truth], "a": prep.src[in_truth]}),
            pd.DataFrame({"r": prep.ring_id[in_truth], "a": prep.dst[in_truth]}),
        ]
    ).drop_duplicates()
    truth = {int(r): np.sort(g["a"].to_numpy("int64")) for r, g in pairs.groupby("r")}
    return SplitCtx(
        name=split, event_id=prep.event_id[rows], minutes=prep.minutes[rows], src=prep.src[rows],
        dst=prep.dst[rows], amount_inr=prep.amount_inr[rows], y=prep.y[rows].astype("int64"),
        ring_id=prep.ring_id[rows], n_accounts=len(prep.categories), truth=truth,
    )  # fmt: skip


def extraction_settings(settings: Settings) -> ExtractionSettings:
    return ExtractionSettings(
        min_size=settings.ring_min_size, cap=settings.community_cap,
        resolution=settings.louvain_resolution, seed=settings.seed,
        taus=tuple(sorted({0.3, 0.5, 0.7, settings.ring_tau})),
    )  # fmt: skip


def cost_params(settings: Settings) -> CostParams:
    return CostParams(settings.review_cost_inr, settings.fp_cost_inr, settings.loss_capture_rate)


# ------------------------------------------------------------------ D7
def _fit_and_score_xgb(prep, tables, vault, variant, settings, name):
    """Fit on train (negatives sampled), early-stop on validation, score val and test once."""
    view = vault.fit_view()
    tr_rows, va_rows = view["train"], view["val"]
    seed = settings.seed
    keep_tr = sample_rows(prep.y[tr_rows], settings.neg_sample_frac, seed)
    keep_va = sample_rows(prep.y[va_rows], settings.neg_sample_frac, seed + 1)
    x_tr = matrix_for(prep, tables, tr_rows[keep_tr], "train", variant)
    x_va = matrix_for(prep, tables, va_rows[keep_va], "val", variant)
    model = fit_xgb(x_tr, prep.y[tr_rows][keep_tr], x_va, prep.y[va_rows][keep_va], seed)
    del x_tr, x_va

    def score(rows, window):
        return score_chunks(
            xgb_predict(model),
            lambda a, b: matrix_for(prep, tables, rows[a:b], window, variant),
            len(rows),
        )

    s_val = score(va_rows, "val")
    s_test = score(vault.release_test(name), "test")
    info = {
        "variant": variant,
        "train_rows_used": int(len(keep_tr)),
        "train_positives": int(prep.y[tr_rows][keep_tr].sum()),
        "best_iteration": int(model.best_iteration),
        "neg_sample_frac": settings.neg_sample_frac,
    }
    return model, s_val, s_test, info


def _importance(model: XGBClassifier, names: list[str], top: int = 15) -> list[dict]:
    gain = model.get_booster().get_score(importance_type="gain")
    rows = [(names[int(k[1:])], float(v)) for k, v in gain.items()]
    rows.sort(key=lambda t: -t[1])
    return [{"feature": f, "gain": g} for f, g in rows[:top]]


def make_vault(prep: Prepared) -> SplitVault:
    return SplitVault(
        {"train": prep.rows("train"), "val": prep.rows("val")},
        test_loader=lambda: prep.rows("test"),
    )


def run_detect(settings: Settings, prep: Prepared | None = None, tables=None) -> dict:
    prep = prep or load_prepared(settings)
    if tables is None:
        features = pd.read_parquet(settings.features_path)
        tables = load_tables(prep, features)
    vault = make_vault(prep)
    settings.models_dir.mkdir(parents=True, exist_ok=True)
    scores: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    report: dict = {"detectors": {}, "seed": settings.seed}
    view = vault.fit_view()

    # velocity rule: trailing 24-hour transfers by the sender (no fitting)
    col = TABULAR_COLUMNS.index(VELOCITY_COLUMN)
    scores["velocity"] = (
        prep.tab[view["val"], col].astype("float32"),
        prep.tab[vault.release_test("velocity"), col].astype("float32"),
    )
    report["detectors"]["velocity"] = {"variant": "rule", "column": VELOCITY_COLUMN}

    for name, variant in (("xgb_tabular", "tabular"), ("xgb_graph", "graph")):
        fitted = _fit_and_score_xgb(prep, tables, vault, variant, settings, name)
        model, s_val, s_test, info = fitted
        names = feature_names(tables.columns, *VARIANTS[variant])
        model.save_model(settings.models_dir / f"{name}.json")
        _write_json(settings.models_dir / f"{name}.features.json", names)
        info["top_features_by_gain"] = _importance(model, names)
        report["detectors"][name] = info
        scores[name] = (s_val, s_test)

    # Isolation Forest: unsupervised, uniform train sample (label-blind), same features as graph
    rng = np.random.default_rng(settings.seed)
    tr_rows = view["train"]
    take = min(IFOREST_TRAIN_ROWS, len(tr_rows))
    pick = np.sort(rng.choice(len(tr_rows), size=take, replace=False))
    forest = ImputedIsolationForest(settings.seed).fit(
        matrix_for(prep, tables, tr_rows[pick], "train", "graph")
    )
    joblib.dump(forest, settings.models_dir / "iforest.joblib")

    def iforest_scores(rows, window):
        return score_chunks(
            forest.predict, lambda a, b: matrix_for(prep, tables, rows[a:b], window, "graph"),
            len(rows),
        )

    scores["iforest"] = (
        iforest_scores(view["val"], "val"),
        iforest_scores(vault.release_test("iforest"), "test"),
    )
    report["detectors"]["iforest"] = {"variant": "unsupervised", "train_rows_used": int(take)}

    write_scores(settings.scores_path, prep, scores)
    report["val_pr_auc"] = {
        k: average_precision(prep.y[view["val"]], v[0]) for k, v in scores.items()
    }
    report["stage01_reference"] = _stage01_reference(settings)
    write_report(settings.detect_report_path, report)
    return report


def write_scores(path, prep: Prepared, scores: dict[str, tuple[np.ndarray, np.ndarray]]) -> None:
    val_rows, test_rows = prep.rows("val"), prep.rows("test")
    frame = pd.DataFrame(
        {
            "event_id": np.concatenate([prep.event_id[val_rows], prep.event_id[test_rows]]),
            "split": np.repeat(["val", "test"], [len(val_rows), len(test_rows)]),
        }
    )
    for name, (s_val, s_test) in scores.items():
        frame[name] = np.concatenate([s_val, s_test]).astype("float32")
    frame.to_parquet(path, index=False)


def read_scores(path, prep: Prepared) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    frame = pd.read_parquet(path)
    out = {}
    for split_name, rows in (("val", prep.rows("val")), ("test", prep.rows("test"))):
        part = frame[frame["split"] == split_name]
        if not np.array_equal(part["event_id"].to_numpy("int64"), prep.event_id[rows]):
            raise ValueError(
                f"{path.name} does not match the current events. Rerun the detect step."
            )
        for name in frame.columns.difference(["event_id", "split"]):
            out.setdefault(name, [None, None])[0 if split_name == "val" else 1] = part[
                name
            ].to_numpy("float32")
    return {k: (v[0], v[1]) for k, v in out.items()}


def _stage01_reference(settings: Settings):
    path = settings.baseline_metrics_path
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# ------------------------------------------------------------------ D8 + D9
def _score_context(prep, scores, settings):
    ext = extraction_settings(settings)
    val_ctx, test_ctx = split_ctx(prep, "val"), split_ctx(prep, "test")
    scored = {
        name: (Scored(val_ctx, s_val, ext), Scored(test_ctx, s_test, ext))
        for name, (s_val, s_test) in scores.items()
    }
    return val_ctx, test_ctx, scored


def run_evaluate(settings: Settings, prep: Prepared | None = None, tables=None) -> dict:
    prep = prep or load_prepared(settings)
    scores = read_scores(settings.scores_path, prep)
    params = cost_params(settings)
    val_ctx, test_ctx, scored = _score_context(prep, scores, settings)
    all_minutes = np.sort(prep.minutes)

    detectors, sweeps, latency = {}, {}, {}
    for name in DETECTORS:
        val, test = scored[name]
        detectors[name] = evaluate_detector(val, test, params)
        sweeps[name] = cost_sweep(val, test)
        theta = detectors[name]["thresholds"]["f1"]
        latency[name] = latency_block(test, theta, all_minutes)

    metrics = {
        "meta": metrics_meta(settings, prep, val_ctx, test_ctx),
        "detectors": detectors,
        "cost_sweep": sweeps,
    }
    write_report(settings.metrics_path, metrics)
    write_report(settings.latency_path, latency)
    if tables is None:  # the graph detector's ring explanations need the feature values
        tables = load_tables(prep, pd.read_parquet(settings.features_path))
    rings = rings_payload(settings, prep, tables, scored["xgb_graph"][1], detectors["xgb_graph"])
    write_report(settings.rings_path, rings)
    settings.results_table_path.write_text(format_results_table(metrics), encoding="utf-8")
    return metrics


def metrics_meta(settings, prep, val_ctx, test_ctx) -> dict:
    return {
        "dataset_variant": settings.dataset_variant,
        "seed": settings.seed,
        "hub_cap": effective_hub_cap(settings),
        "cost_assumptions_inr": {
            "review_cost_inr": settings.review_cost_inr, "fp_cost_inr": settings.fp_cost_inr,
            "loss_capture_rate": settings.loss_capture_rate,
            "note": "Planning assumptions, not measured. amount_inr uses placeholder FX rates.",
        },
        "ring_tau": settings.ring_tau,
        "ring_min_size": settings.ring_min_size,
        "community_cap": settings.community_cap,
        "neg_sample_frac": settings.neg_sample_frac,
        "rows": {"val": int(len(val_ctx.y)), "test": int(len(test_ctx.y))},
        "positives": {"val": int(val_ctx.y.sum()), "test": int(test_ctx.y.sum())},
        "pattern_rings": {"val": len(val_ctx.truth), "test": len(test_ctx.truth)},
        "protocol": "fit on train; early stopping and every threshold on validation; "
        "test scored once per detector at fixed thresholds",
        "positive_rate_note": "The positive rate rises across splits; test is not train-like.",
        "ring_scope": "Ring recall is measured on pattern rings only; unringed positives "
        "count in transaction-level metrics only.",
    }  # fmt: skip


def rings_payload(settings, prep, tables, scored_test: Scored, report: dict) -> dict:
    """Rings of the graph detector at the net-value threshold on the test split (D8)."""
    theta = report["thresholds"]["net_value"]
    payload: dict = {
        "detector": "xgb_graph", "split": "test", "threshold": theta,
        "threshold_kind": "net_value (chosen on validation)", "rings": [],
    }  # fmt: skip
    if not np.isfinite(theta):
        payload["note"] = "The validation net-value rule chose to flag nothing."
        return payload
    rings = scored_test.rings(theta)
    names_path = settings.models_dir / "xgb_graph.features.json"
    contribs = None
    if tables is not None and rings:
        model = XGBClassifier()
        model.load_model(settings.models_dir / "xgb_graph.json")
        names = json.loads(names_path.read_text(encoding="utf-8"))
        rows_local = np.concatenate([r.rows for r in rings])
        test_rows = prep.rows("test")
        x = matrix_for(prep, tables, test_rows[rows_local], "test", "graph")
        raw = model.get_booster().predict(DMatrix(x, feature_names=names), pred_contribs=True)
        contribs = {int(i): raw[k, :-1] for k, i in enumerate(rows_local)}
    ctx = scored_test.ctx
    for i, ring in enumerate(rings):
        entry = {
            "ring_index": i, "score": ring.score, "n_members": int(len(ring.members)),
            "n_transfers": int(len(ring.rows)), "amount_inr": ring.amount_inr,
            "oversized": ring.oversized,
            "members": [str(prep.categories[c]) for c in ring.members[:500]],
            "event_ids": [int(e) for e in ctx.event_id[ring.rows][:500]],
        }  # fmt: skip
        if contribs is not None:
            mean = np.mean([contribs[int(r)] for r in ring.rows[:200]], axis=0)
            top = np.argsort(-np.abs(mean), kind="stable")[:5]
            entry["top_features"] = [
                {"feature": names[j], "mean_contribution": float(mean[j])} for j in top
            ]
        payload["rings"].append(entry)
    return payload


# ------------------------------------------------------------------ ablation
def build_uncontrolled_features(settings: Settings, events: pd.DataFrame | None = None):
    """Features with hub control OFF: no degree cap and uniform edge weights (all 1)."""
    from ringsentinel.stage02 import load_events

    events = events if events is not None else load_events(settings)
    frames = []
    for window in WINDOW_SPLITS:
        win = cumulative_events(events, window)
        own = events[events["split"] == window]
        graph = build_graph(win[list(GRAPH_EVENT_COLUMNS)], hub_cap=10**9)
        graph = dataclasses.replace(graph, und_weight=np.ones_like(graph.und_weight))
        nodes = node_features(graph)
        kept = graph.und_kept
        community, oversized = detect_communities(
            graph.n, graph.und_a[kept], graph.und_b[kept], graph.und_weight[kept],
            graph.is_hub, settings.community_cap, settings.louvain_resolution, settings.seed,
        )  # fmt: skip
        comm_table = community_features(graph, community, oversized, nodes)
        frame = pd.concat([nodes, attach_to_nodes(community, comm_table)], axis=1)
        frame.insert(0, "community_id", community.astype("int32"))
        frame.insert(0, "account", graph.accounts.to_numpy())
        active = pd.Index(
            pd.unique(pd.concat([own["src_account"].astype(str), own["dst_account"].astype(str)]))
        )
        frame = frame[frame["account"].isin(active)].reset_index(drop=True)
        frame.insert(0, "window", window)
        frames.append(frame)
    features = pd.concat(frames, ignore_index=True)
    features["window"] = pd.Categorical(features["window"], categories=list(WINDOW_SPLITS))
    return features


def run_ablate(settings: Settings, prep: Prepared | None = None, tables=None) -> dict:
    prep = prep or load_prepared(settings)
    main_features = pd.read_parquet(settings.features_path)
    columns = graph_columns(main_features)
    if tables is None:
        tables = load_tables(prep, main_features, columns)
    if settings.features_nohub_path.exists():
        nohub_features = pd.read_parquet(settings.features_nohub_path)
    else:
        nohub_features = build_uncontrolled_features(settings)
        nohub_features.to_parquet(settings.features_nohub_path, index=False)
    nohub = load_tables(prep, nohub_features, columns)

    scores = read_scores(settings.scores_path, prep)
    vault = make_vault(prep)
    fitted = _fit_and_score_xgb(prep, nohub, vault, "graph", settings, "xgb_graph_nohub")
    _, s_val, s_test, info = fitted
    abl_scores = {
        "xgb_tabular": scores["xgb_tabular"],
        "xgb_graph_nohub": (s_val, s_test),
        "xgb_graph": scores["xgb_graph"],
    }
    write_scores(settings.scores_ablation_path, prep, abl_scores)

    params = cost_params(settings)
    _, _, scored = _score_context(prep, abl_scores, settings)
    rows = {}
    labels = {
        "xgb_tabular": "graph features OFF (tabular only)",
        "xgb_graph_nohub": "graph features ON, hub control OFF",
        "xgb_graph": "graph features ON, hub control ON",
    }
    for name in ABLATION_DETECTORS:
        val, test = scored[name]
        full = evaluate_detector(val, test, params, with_ring_curve=False)
        rows[name] = {"label": labels[name], **_ablation_summary(full)}
    result = {
        "protocol": "same model class, seed and thresholds-from-validation rule; test scored once",
        "hub_control_off": "no degree cap and all edge weights set to 1",
        "variants": rows,
        "nohub_fit": info,
        "hub_cap_on": effective_hub_cap(settings),
    }
    write_report(settings.ablations_path, result)
    return result


def _ablation_summary(full: dict) -> dict:
    f1_point = full["operating_points"]["f1"]["test"]
    nv_point = full["operating_points"]["net_value"]["test"]
    return {
        "val_pr_auc": full["val"]["pr_auc"],
        "test_pr_auc": full["test"]["pr_auc"],
        "test_prevalence": full["test"]["prevalence"],
        "test_at_val_f1_threshold": {
            k: full["test"]["at_f1_threshold"][k] for k in ("precision", "recall", "f1")
        },
        "test_rings_at_f1_threshold": f1_point["by_tau"],
        "test_ring_size_at_f1_threshold": f1_point["ring_size"],
        "test_net_value_inr_at_nv_threshold": nv_point["net_value_inr"],
        "test_rings_at_nv_threshold": nv_point["predicted_rings"],
    }


# ------------------------------------------------------------------ robustness
def run_robustness(
    settings: Settings, prep: Prepared | None = None, events: pd.DataFrame | None = None
) -> dict:
    """Edge dropout on the test-window graph, for testing only (never for tuning evasion).

    A seeded share of the transfers is removed before the graph and features of the test
    window are rebuilt; the fitted graph model and the validation-chosen thresholds stay fixed.
    """
    from ringsentinel.stage02 import load_events

    prep = prep or load_prepared(settings)
    events = events if events is not None else load_events(settings)
    metrics = json.loads(settings.metrics_path.read_text(encoding="utf-8"))
    base = metrics["detectors"]["xgb_graph"]
    theta_f1 = float(base["thresholds"]["f1"])
    theta_nv = base["thresholds"]["net_value"]
    theta_nv = float("inf") if isinstance(theta_nv, str) else float(theta_nv)

    features = pd.read_parquet(settings.features_path)
    columns = graph_columns(features)
    model = XGBClassifier()
    model.load_model(settings.models_dir / "xgb_graph.json")
    hub_cap = effective_hub_cap(settings)
    ext = extraction_settings(settings)
    test_ctx = split_ctx(prep, "test")
    test_rows = prep.rows("test")
    window_events = cumulative_events(events, "test")
    all_levels = []
    for level in ROBUSTNESS_LEVELS:
        rng = np.random.default_rng(settings.seed + int(round(level * 1000)))
        keep = rng.random(len(window_events)) >= level
        frame, *_ = build_window_features(
            window_events[keep][list(GRAPH_EVENT_COLUMNS)], hub_cap, settings.community_cap,
            settings.louvain_resolution, settings.seed,
        )  # fmt: skip
        frame.insert(0, "window", "test")
        table = window_table(frame, "test", columns)
        tables = FeatureTables({"test": table}, {"test": table.rows_for(prep.categories)}, columns)
        s_test = score_chunks(
            xgb_predict(model),
            lambda a, b, tables=tables: matrix_for(prep, tables, test_rows[a:b], "test", "graph"),
            len(test_rows),
        )
        scored = Scored(test_ctx, s_test, ext)
        entry: dict = {
            "dropout": level, "events_kept": int(keep.sum()),
            "test_pr_auc": average_precision(test_ctx.y, s_test),
        }  # fmt: skip
        f1_point = precision_recall_f1(test_ctx.y, s_test >= theta_f1)
        entry["at_val_f1_threshold"] = {
            k: f1_point[k] for k in ("flagged", "precision", "recall", "f1")
        }
        entry["rings_at_f1_threshold"] = ring_block(scored, theta_f1)["by_tau"]
        if np.isfinite(theta_nv):
            entry["rings_at_nv_threshold"] = ring_block(scored, theta_nv)["by_tau"]
        all_levels.append(entry)
    base_pr = all_levels[0]["test_pr_auc"]
    for entry in all_levels:
        entry["pr_auc_relative_to_no_dropout"] = entry["test_pr_auc"] / base_pr if base_pr else None
    result = {
        "purpose": "Robustness test only: measures metric decay when part of the transfer graph "
        "is unobserved. Not an evasion tool and never used for tuning.",
        "perturbation": "random removal of a share of transfers from the test-window graph; "
        "tabular features stay unperturbed",
        "levels": all_levels,
        "reference_test_pr_auc_unperturbed_run": base["test"]["pr_auc"],
    }
    write_report(settings.robustness_path, result)
    return result


# ------------------------------------------------------------------ tables
def _fmt(value, digits=4):
    if value is None:
        return "n/a"
    if isinstance(value, str):
        return value
    return f"{value:.{digits}f}"


def format_results_table(metrics: dict) -> str:
    """Markdown comparison table for all detectors on the temporal test split."""
    meta = metrics["meta"]
    tau = f"{meta['ring_tau']:g}"
    lines = [
        f"Test split: {meta['rows']['test']:,} transfers, {meta['positives']['test']:,} "
        f"positives (prevalence {meta['positives']['test'] / meta['rows']['test']:.5f}).",
        f"Thresholds were chosen on validation only. Ring metrics: pattern rings only, "
        f"Jaccard tau {tau}.",
        "",
        "| Detector | Val PR-AUC | Test PR-AUC | Test P | Test R | Test F1 | Rings P | "
        "Rings R | Net value (INR) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, d in metrics["detectors"].items():
        t = d["test"]["at_f1_threshold"]
        ring = d["operating_points"]["f1"]["test"]["by_tau"][tau]
        nv = d["operating_points"]["net_value"]["test"]["net_value_inr"]
        lines.append(
            f"| {name} | {_fmt(d['val']['pr_auc'])} | {_fmt(d['test']['pr_auc'])} | "
            f"{_fmt(t['precision'])} | {_fmt(t['recall'])} | {_fmt(t['f1'])} | "
            f"{_fmt(ring['precision'])} | {_fmt(ring['recall'])} | {nv:,.0f} |"
        )
    lines += [
        "",
        "Test P, R, F1: transaction level at the validation F1 threshold. Rings P and R: "
        "ring level at that threshold. Net value: at the validation net-value threshold with "
        "the stated rupee assumptions. Validation PR-AUC is optimistic.",
    ]
    return "\n".join(lines) + "\n"


def format_full_results(
    metrics: dict, ablations: dict | None, robustness: dict | None, latency: dict | None
) -> str:
    """Markdown for docs/EVALUATION_RESULTS.md, generated from the JSON files only."""
    meta = metrics["meta"]
    tau = f"{meta['ring_tau']:g}"
    out = [
        "# Evaluation results (generated)",
        "",
        "Generated by `scripts/reproduce.py` from the JSON files in the processed folder. "
        "Do not edit by hand. Numbers are valid only for the dataset variant, seed and platform "
        "named below; XGBoost can differ slightly between platforms.",
        "",
        f"Variant: {meta['dataset_variant']}; seed {meta['seed']}; hub cap {meta['hub_cap']}; "
        f"ring match tau {tau}; ring minimum size {meta['ring_min_size']}.",
        f"Rupee assumptions (planning values, not measurements): review "
        f"INR {meta['cost_assumptions_inr']['review_cost_inr']:,.0f}, false-positive account "
        f"INR {meta['cost_assumptions_inr']['fp_cost_inr']:,.0f}, loss capture rate "
        f"{meta['cost_assumptions_inr']['loss_capture_rate']:g}. Amounts use placeholder FX rates.",
        "",
        "## All detectors on the temporal test split",
        "",
        format_results_table(metrics).rstrip(),
        "",
    ]
    if latency:
        out += [
            "## Detection latency (retrospective lower bound)",
            "",
            "| Detector | Pattern rings with a flagged transfer | Median events | P90 events |",
            "| --- | --- | --- | --- |",
        ]
        for name, row in latency.items():
            out.append(
                f"| {name} | {row['rings_with_a_flagged_transfer']} of {row['truth_rings']} | "
                f"{_fmt(row['events_median'], 0)} | {_fmt(row['events_p90'], 0)} |"
            )
        out.append("")
    if ablations:
        out += [
            "## Ablation",
            "",
            "| Variant | Val PR-AUC | Test PR-AUC | Test F1 | Ring P | Ring R | "
            "Median ring size | Net value (INR) |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for row in ablations["variants"].values():
            ring = row["test_rings_at_f1_threshold"][tau]
            out.append(
                f"| {row['label']} | {_fmt(row['val_pr_auc'])} | {_fmt(row['test_pr_auc'])} | "
                f"{_fmt(row['test_at_val_f1_threshold']['f1'])} | {_fmt(ring['precision'])} | "
                f"{_fmt(ring['recall'])} | {row['test_ring_size_at_f1_threshold']['median']:g} | "
                f"{row['test_net_value_inr_at_nv_threshold']:,.0f} |"
            )
        out.append("")
    if robustness:
        out += [
            "## Robustness: random removal of transfers from the test-window graph",
            "",
            "Testing only; not an evasion tool.",
            "",
            "| Dropout | Test PR-AUC | Relative to no dropout | F1 at val threshold | Ring R |",
            "| --- | --- | --- | --- | --- |",
        ]
        for lv in robustness["levels"]:
            ring = lv["rings_at_f1_threshold"][tau]
            out.append(
                f"| {lv['dropout']:.0%} | {_fmt(lv['test_pr_auc'])} | "
                f"{_fmt(lv['pr_auc_relative_to_no_dropout'], 3)} | "
                f"{_fmt(lv['at_val_f1_threshold']['f1'])} | {_fmt(ring['recall'])} |"
            )
        out.append("")
    sweep = metrics["cost_sweep"].get("xgb_graph", [])
    if sweep:
        out += [
            "## Cost sensitivity (xgb_graph; threshold re-chosen on validation per setting)",
            "",
            "| Capture | Review INR | FP INR | Flags nothing | Test rings | Caught | "
            "Legit accounts in rings | Test net value (INR) |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for r in sweep:
            out.append(
                f"| {r['capture_rate']:g} | {r['review_cost_inr']:,.0f} | "
                f"{r['fp_cost_inr']:,.0f} | "
                f"{'yes' if r['flags_nothing'] else 'no'} | {r['test_rings']} | "
                f"{r['test_caught_rings']} | {r['test_legit_accounts_in_rings']} | "
                f"{r['test_net_value_inr']:,.0f} |"
            )
        out.append("")
    return "\n".join(out) + "\n"


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def numeric_differences(old, new, path: str = "", tol: float = 0.0, limit: int = 25) -> list[str]:
    """Paths where two JSON-like objects differ (used by scripts/reproduce.py)."""
    diffs: list[str] = []

    def walk(a, b, where):
        if len(diffs) >= limit:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b)):
                if key not in a or key not in b:
                    diffs.append(f"{where}/{key}: present in only one run")
                else:
                    walk(a[key], b[key], f"{where}/{key}")
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                diffs.append(f"{where}: length {len(a)} vs {len(b)}")
            else:
                for i, (x, y) in enumerate(zip(a, b, strict=True)):
                    walk(x, y, f"{where}[{i}]")
        elif _is_number(a) and _is_number(b):
            if abs(a - b) > tol:
                diffs.append(f"{where}: {a} vs {b}")
        elif a != b:
            diffs.append(f"{where}: {a!r} vs {b!r}")

    walk(old, new, path)
    return diffs
