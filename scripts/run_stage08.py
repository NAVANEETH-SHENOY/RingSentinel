"""Run Stage 08 (second dataset: Elliptic) from the command line. Repo root, venv active.

    python scripts\\run_stage08.py verify                  # inspect the real files and print them
    python scripts\\run_stage08.py verify --write-manifest # also record sizes and SHA-256
    python scripts\\run_stage08.py run                     # all detectors + ablation
    python scripts\\run_stage08.py run --gnn               # also the optional GraphSAGE
    python scripts\\run_stage08.py table                   # two-dataset results table
    python scripts\\run_stage08.py demo                    # SYNTHETIC dry run, no download needed

Put the three Kaggle files in data\\raw\\elliptic (or set RS_ELLIPTIC_DIR). Nothing here touches
the IBM AML outputs. The test steps are scored once per detector (see docs/STAGE_08.md).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from ringsentinel.config import get_settings  # noqa: E402
from ringsentinel.elliptic import schema as sc  # noqa: E402
from ringsentinel.elliptic.load import (  # noqa: E402
    _first_line,
    assemble,
    read_classes,
    read_edges,
    read_features,
)
from ringsentinel.elliptic.pipeline import (  # noqa: E402
    cross_dataset_table,
    format_results,
    run_elliptic,
)
from ringsentinel.elliptic.settings import (  # noqa: E402
    EllipticSettings,
    load_elliptic_settings,
)
from ringsentinel.ingest.manifest import (  # noqa: E402
    add_variant,
    load_manifest,
    save_manifest,
    verify_files,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TABLE_PATH = PROJECT_ROOT / "docs" / "RESULTS_TABLE.md"


def cmd_verify(settings: EllipticSettings, write_manifest: bool) -> int:
    missing = [n for n in sc.RAW_FILES if not (settings.raw_dir / n).exists()]
    if missing:
        print(f"Missing in {settings.raw_dir}: {', '.join(missing)}")
        print("Download the Elliptic Data Set from Kaggle and unzip the three CSV files there.")
        return 1
    for name in sc.RAW_FILES:
        path = settings.raw_dir / name
        head = _first_line(path)
        shown = head if len(head) <= 6 else head[:4] + ["..."] + head[-1:]
        print(f"{name}: {path.stat().st_size:,} bytes; first row has {len(head)} cells: {shown}")
    try:
        data = assemble(
            read_features(settings.features_path),
            read_classes(settings.classes_path),
            read_edges(settings.edgelist_path),
        )
    except (sc.EllipticSchemaError, ValueError) as exc:
        print(f"SCHEMA PROBLEM: {exc}")
        return 1
    print(json.dumps(data.report, indent=2))
    paths = [settings.raw_dir / n for n in sc.RAW_FILES]
    if write_manifest:
        manifest = add_variant(load_manifest(settings.manifest_path), "elliptic", paths)
        save_manifest(settings.manifest_path, manifest)
        print(f"Wrote {settings.manifest_path}")
    elif settings.manifest_path.exists():
        problems = verify_files(load_manifest(settings.manifest_path), "elliptic", settings.raw_dir)
        print("Manifest: OK" if not problems else "Manifest problems:\n  " + "\n  ".join(problems))
        return 1 if problems else 0
    print("Layout looks as expected. Now check the licence on the Kaggle page (docs/DATA.md).")
    return 0


def cmd_run(settings: EllipticSettings, with_gnn: bool, with_ablation: bool) -> int:
    extra = None
    if with_gnn:
        from ringsentinel.elliptic.gnn import build_graphsage, torch_available

        if not torch_available():
            print("PyTorch is not installed. Run: pip install -r requirements-gnn.txt")
            return 1
        extra = {"graphsage": build_graphsage}
    metrics = run_elliptic(settings, with_ablation=with_ablation, extra=extra)
    print(format_results(metrics))
    print(f"Wrote {settings.metrics_path}")
    return 0


def cmd_table() -> int:
    core = get_settings()
    ell = load_elliptic_settings()
    ibm = json.loads(core.metrics_path.read_text("utf-8")) if core.metrics_path.exists() else None
    elliptic = (
        json.loads(ell.metrics_path.read_text("utf-8")) if ell.metrics_path.exists() else None
    )
    text = cross_dataset_table(ibm, elliptic)
    TABLE_PATH.write_text(text, encoding="utf-8")
    print(text)
    print(f"Wrote {TABLE_PATH}")
    return 0


def cmd_demo(with_gnn: bool) -> int:
    """Run the whole pipeline on SYNTHETIC data in a temporary folder (nothing is kept)."""
    from ringsentinel.elliptic.synthetic import write_synthetic_elliptic

    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "raw" / "elliptic"
        write_synthetic_elliptic(raw)
        core = get_settings(load_env_file=False).model_copy(update={"data_dir": Path(tmp)})
        settings = EllipticSettings(core=core, raw_dir=raw)
        print("SYNTHETIC data: these numbers say nothing about the real Elliptic results.\n")
        return cmd_run(settings, with_gnn, with_ablation=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--write-manifest", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("--gnn", action="store_true")
    r.add_argument("--no-ablation", action="store_true")
    sub.add_parser("table")
    d = sub.add_parser("demo")
    d.add_argument("--gnn", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "table":
        return cmd_table()
    if args.command == "demo":
        return cmd_demo(args.gnn)
    settings = load_elliptic_settings()
    if args.command == "verify":
        return cmd_verify(settings, args.write_manifest)
    return cmd_run(settings, args.gnn, not args.no_ablation)


if __name__ == "__main__":
    raise SystemExit(main())
