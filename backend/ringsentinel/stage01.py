"""Stage 01 orchestration: verify raw files, ingest, split, and score the baselines.

The test split is removed before any feature is computed or any model is fitted
(see prepare_baseline_frames), so baselines cannot touch it.
"""

from __future__ import annotations

import json

import pandas as pd

from ringsentinel.config import Settings
from ringsentinel.evaluation.metrics import best_f1_threshold, evaluate_scores
from ringsentinel.ingest import manifest as manifest_mod
from ringsentinel.ingest.normalize import normalize
from ringsentinel.models.baselines import (
    tabular_features,
    train_xgb,
    velocity_scores,
)
from ringsentinel.split import build_split


def run_write_manifest(settings: Settings) -> dict:
    manifest = manifest_mod.load_manifest(settings.manifest_path)
    manifest_mod.add_variant(
        manifest, settings.dataset_variant, [settings.trans_path, settings.patterns_path]
    )
    manifest_mod.save_manifest(settings.manifest_path, manifest)
    return manifest


def run_verify(settings: Settings) -> list[str]:
    manifest = manifest_mod.load_manifest(settings.manifest_path)
    return manifest_mod.verify_files(manifest, settings.dataset_variant, settings.raw_dir)


def run_ingest(settings: Settings, force: bool = False) -> dict:
    if settings.events_path.exists() and not force:
        return json.loads(settings.ingest_report_path.read_text(encoding="utf-8"))
    return normalize(settings)


def run_split(settings: Settings) -> dict:
    events = pd.read_parquet(settings.events_path, columns=["event_id", "ts", "is_illicit"])
    rings = pd.read_parquet(settings.rings_truth_path)
    split_table, rings, meta = build_split(
        events, rings, settings.train_frac, settings.val_frac
    )
    split_table.to_parquet(settings.split_path, index=False)
    rings.to_parquet(settings.rings_truth_path, index=False)
    settings.split_meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def prepare_baseline_frames(
    events: pd.DataFrame, split_table: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (train events, validation events). Test rows are dropped here and never returned."""
    labelled = events.merge(split_table, on="event_id", how="left", validate="one_to_one")
    train = labelled[labelled["split"] == "train"].reset_index(drop=True)
    val = labelled[labelled["split"] == "val"].reset_index(drop=True)
    return train, val


def _label_note(settings: Settings) -> str:
    """Describe where the labels came from, read from the ingest report (never hard-coded)."""
    source = None
    if settings.ingest_report_path.exists():
        report = json.loads(settings.ingest_report_path.read_text(encoding="utf-8"))
        source = report.get("labels", {}).get("label_source")
    if source == "csv_label_column":
        return (
            "Labels come from the CSV 'Is Laundering' column. The patterns file covers only a "
            "subset of those transactions, so ring labels exist for part of the positives."
        )
    if source == "patterns_file_only":
        return "Labels come from the patterns file only; laundering outside patterns is unlabelled."
    return "Label source unknown: ingest_report.json was missing or has no label_source."


def run_baselines(settings: Settings) -> dict:
    events = pd.read_parquet(settings.events_path)
    split_table = pd.read_parquet(settings.split_path)
    train, val = prepare_baseline_frames(events, split_table)
    del events
    y_train = train["is_illicit"].to_numpy()
    y_val = val["is_illicit"].to_numpy()

    # Velocity rule: the threshold is chosen on validation only.
    # Counts use past events only, so train and validation can be scored together.
    both = pd.concat([train, val], ignore_index=True)
    v_all = velocity_scores(both)
    v_val = v_all[len(train):]
    v_thr, _ = best_f1_threshold(y_val, v_val)
    velocity = evaluate_scores(y_val, v_val, threshold=v_thr)
    velocity["tuned_on_this_split"] = True  # threshold was picked on validation itself

    model = train_xgb(
        tabular_features(train), y_train, tabular_features(val), y_val, seed=settings.seed
    )
    x_scores = model.predict_proba(tabular_features(val))[:, 1]
    xgb_metrics = evaluate_scores(y_val, x_scores)
    xgb_metrics["best_iteration"] = int(model.best_iteration)

    metrics = {
        "variant": settings.dataset_variant,
        "seed": settings.seed,
        "split_rows": {"train": int(len(train)), "val": int(len(val))},
        "train_positives": int(y_train.sum()),
        "velocity_rule": velocity,
        "tabular_xgboost": xgb_metrics,
        "notes": [
            "Validation split only; the test split was not used or scored.",
            "Precision/recall/F1 use the F1-optimal threshold chosen on validation itself, so "
            "they are optimistic. PR-AUC is threshold-free. Compare PR-AUC with prevalence.",
            "XGBoost early stopping also watches validation, a further small optimism.",
            _label_note(settings),
        ],
    }
    settings.baseline_metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics


def format_baseline_table(metrics: dict) -> str:
    rows = [
        ("velocity_rule", metrics["velocity_rule"]),
        ("tabular_xgboost", metrics["tabular_xgboost"]),
    ]
    header = (
        f"{'detector':<18}{'PR-AUC':>9}{'prevalence':>12}{'precision':>11}"
        f"{'recall':>9}{'F1':>8}{'flagged':>9}"
    )
    lines = [
        f"Baselines on the VALIDATION split ({metrics['variant']}, seed {metrics['seed']})",
        header,
    ]
    for name, m in rows:
        lines.append(
            f"{name:<18}{m['pr_auc']:>9.4f}{m['prevalence']:>12.5f}{m['precision']:>11.4f}"
            f"{m['recall']:>9.4f}{m['f1']:>8.4f}{m['flagged']:>9d}"
        )
    lines.append("Precision/recall/F1 are at a validation-tuned threshold (optimistic).")
    return "\n".join(lines)
