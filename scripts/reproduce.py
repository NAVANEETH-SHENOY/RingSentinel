"""Regenerate every Stage 03 number with one command (repo root, venv active).

    python scripts\\reproduce.py                 # fit, evaluate, ablate, robustness, write docs
    python scripts\\reproduce.py --evaluate-only # reuse scores.parquet, redo everything after it

It keeps the previous metrics.json as metrics.previous.json, reruns, and reports whether the
new numbers are identical. It then writes docs\\EVALUATION_RESULTS.md from the JSON files.
Same machine and same inputs should give identical numbers; XGBoost results can differ
slightly between platforms (see docs/EVALUATION.md).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ringsentinel.config import get_settings  # noqa: E402
from ringsentinel.stage03 import (  # noqa: E402
    format_full_results,
    load_prepared,
    numeric_differences,
    run_ablate,
    run_detect,
    run_evaluate,
    run_robustness,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--evaluate-only", action="store_true")
    args = parser.parse_args(argv)
    settings = get_settings()
    needed = (settings.events_path, settings.split_path, settings.rings_truth_path,
              settings.features_path)  # fmt: skip
    missing = [p for p in needed if not p.exists()]
    if missing:
        print("Missing:", *map(str, missing), sep="\n  ")
        print("Run scripts\\run_stage01.py and scripts\\run_stage02.py first.")
        return 1

    previous = settings.processed_dir / "metrics.previous.json"
    had_previous = settings.metrics_path.exists()
    if had_previous:
        shutil.copyfile(settings.metrics_path, previous)

    prep = load_prepared(settings)
    if not args.evaluate_only:
        run_detect(settings, prep)
    run_evaluate(settings, prep)
    if not args.evaluate_only:
        run_ablate(settings, prep)
    run_robustness(settings, prep)

    metrics = json.loads(settings.metrics_path.read_text(encoding="utf-8"))
    ablations = json.loads(settings.ablations_path.read_text(encoding="utf-8"))
    robustness = json.loads(settings.robustness_path.read_text(encoding="utf-8"))
    latency = json.loads(settings.latency_path.read_text(encoding="utf-8"))
    target = ROOT / "docs" / "EVALUATION_RESULTS.md"
    text = format_full_results(metrics, ablations, robustness, latency)
    target.write_text(text, encoding="utf-8")
    print(f"Wrote {settings.metrics_path} and {target}")

    if had_previous:
        old = json.loads(previous.read_text(encoding="utf-8"))
        diffs = numeric_differences(old, metrics)
        if diffs:
            print("NOT IDENTICAL to the previous metrics.json (first differences):")
            for line in diffs:
                print("  ", line)
            return 2
        print("REPRODUCED: metrics.json is identical to the previous run.")
    else:
        print("No previous metrics.json to compare with; run this script again to check.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
