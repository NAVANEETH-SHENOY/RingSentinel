r"""Export the snapshot bundle (data stage D12) from the Stage 03 outputs.

Usage (repo root, cmd):  python scripts\export_snapshots.py [--git-commit SHA] [--frozen]
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ringsentinel.config import get_settings  # noqa: E402
from ringsentinel.snapshots.bundle import SnapshotError  # noqa: E402
from ringsentinel.snapshots.export import DEFAULT_MAX_RINGS, export_snapshots  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None, help="default: data/snapshots")
    parser.add_argument("--git-commit", default=os.environ.get("RS_GIT_COMMIT", ""))
    parser.add_argument("--frozen", action="store_true", help="mark numbers as frozen")
    parser.add_argument("--max-rings", type=int, default=DEFAULT_MAX_RINGS)
    parser.add_argument("--no-edges", action="store_true", help="skip reading events.parquet")
    args = parser.parse_args(argv)
    settings = get_settings()
    args.git_commit = args.git_commit.strip() or "unknown"
    try:
        bundle = export_snapshots(
            settings, args.out, git_commit=args.git_commit, frozen=args.frozen,
            max_rings=args.max_rings, with_edges=not args.no_edges,
        )  # fmt: skip
    except SnapshotError as exc:
        print(f"EXPORT FAILED: {exc}")
        return 1
    meta = bundle.meta
    print(f"bundle_id      {meta['bundle_id']}")
    print(f"written to     {bundle.directory}")
    print(f"rings          {meta['n_rings_exported']} exported of {meta['n_rings_total']}")
    print(f"evaluation_frozen = {meta['evaluation_frozen']}, git_commit = {meta['git_commit']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
