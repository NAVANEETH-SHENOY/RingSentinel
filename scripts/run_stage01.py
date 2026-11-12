"""Run Stage 01 from the command line (repo root, venv active).

    python scripts\\run_stage01.py                  # verify, ingest, split, baselines
    python scripts\\run_stage01.py --step ingest    # one step only
    python scripts\\run_stage01.py --write-manifest # record checksums for the current variant
    python scripts\\run_stage01.py --force          # redo ingest even if events.parquet exists

The variant comes from RS_DATASET_VARIANT (default HI-Small).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make the backend package importable when this script is run directly (not via pytest).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from ringsentinel.config import get_settings  # noqa: E402
from ringsentinel.stage01 import (  # noqa: E402
    format_baseline_table,
    run_baselines,
    run_ingest,
    run_split,
    run_verify,
    run_write_manifest,
)

STEPS = ("verify", "ingest", "split", "baselines")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--step", choices=(*STEPS, "all"), default="all")
    parser.add_argument("--force", action="store_true", help="redo ingest")
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args(argv)
    settings = get_settings()
    print(f"Variant: {settings.dataset_variant}   data dir: {settings.data_dir}")

    if args.write_manifest:
        run_write_manifest(settings)
        print(f"Wrote checksums to {settings.manifest_path}")
        return 0

    wanted = STEPS if args.step == "all" else (args.step,)

    if "verify" in wanted:
        problems = run_verify(settings)
        if problems:
            print("Raw file check FAILED:")
            for item in problems:
                print(f"  - {item}")
            return 1
        print("Raw files match MANIFEST.json")

    if "ingest" in wanted:
        report = run_ingest(settings, force=args.force)
        labels = report["labels"]
        print(
            f"Ingest: {report['profile']['n_events']:,} events, "
            f"{labels['illicit_events']:,} illicit ({labels['label_rate']:.5%}), "
            f"{report['rings']['n_rings']} rings, label source: {labels['label_source']}, "
            f"unmatched pattern lines: {labels['pattern_lines_unmatched']}"
        )
        print(f"Full report: {settings.ingest_report_path}")

    if "split" in wanted:
        meta = run_split(settings)
        keys = ("rows", "illicit_rows", "rings_by_split")
        print("Split:", json.dumps({k: meta[k] for k in keys}))
        print("Cuts:", meta["cuts"])

    if "baselines" in wanted:
        metrics = run_baselines(settings)
        print(format_baseline_table(metrics))
        print(f"Saved: {settings.baseline_metrics_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
