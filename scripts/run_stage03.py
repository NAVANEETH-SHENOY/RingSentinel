"""Run Stage 03 from the command line (repo root, venv active; Stage 01 and 02 outputs needed).

    python scripts\\run_stage03.py                      # detect, evaluate, ablate, robustness
    python scripts\\run_stage03.py --step detect        # one step only
    python scripts\\run_stage03.py --step evaluate

Steps, in order: detect (D7: fit and score the four detectors), evaluate (D8 + D9: thresholds,
rings, metrics, cost, latency), ablate (hub control and graph features on/off), robustness
(edge dropout). Every threshold is chosen on validation; the test split is scored once.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from ringsentinel.config import get_settings  # noqa: E402
from ringsentinel.stage03 import (  # noqa: E402
    load_prepared,
    run_ablate,
    run_detect,
    run_evaluate,
    run_robustness,
)

STEPS = ("detect", "evaluate", "ablate", "robustness")


def check_inputs(settings) -> list[Path]:
    needed = (
        settings.events_path, settings.split_path, settings.rings_truth_path,
        settings.features_path,
    )  # fmt: skip
    return [p for p in needed if not p.exists()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--step", choices=(*STEPS, "all"), default="all")
    args = parser.parse_args(argv)
    settings = get_settings()
    print(f"Variant: {settings.dataset_variant}   data dir: {settings.data_dir}")
    missing = check_inputs(settings)
    if missing:
        for path in missing:
            print(f"Missing {path}")
        print("Run scripts\\run_stage01.py and scripts\\run_stage02.py first.")
        return 1
    wanted = STEPS if args.step == "all" else (args.step,)
    prep = load_prepared(settings)
    print(f"Loaded {prep.n:,} events.")

    if "detect" in wanted:
        report = run_detect(settings, prep)
        print("Validation PR-AUC (optimistic: early stopping used validation):")
        for name, value in report["val_pr_auc"].items():
            print(f"  {name:<12} {value:.5f}")
        print(f"Saved: {settings.scores_path}")
    if "evaluate" in wanted:
        metrics = run_evaluate(settings, prep)
        print(settings.results_table_path.read_text(encoding="utf-8"))
        print(f"Saved: {settings.metrics_path}, {settings.rings_path}, {settings.latency_path}")
        _ = metrics
    if "ablate" in wanted:
        result = run_ablate(settings, prep)
        for row in result["variants"].values():
            print(f"  {row['label']:<42} test PR-AUC {row['test_pr_auc']:.5f}")
        print(f"Saved: {settings.ablations_path}")
    if "robustness" in wanted:
        result = run_robustness(settings, prep)
        for lv in result["levels"]:
            print(f"  dropout {lv['dropout']:.0%}: test PR-AUC {lv['test_pr_auc']:.5f}")
        print(f"Saved: {settings.robustness_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
