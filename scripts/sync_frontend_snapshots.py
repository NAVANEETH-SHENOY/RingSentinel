r"""Copy the validated snapshot bundle into the frontend so it works with the backend off.

Usage (repo root, cmd):  python scripts\sync_frontend_snapshots.py [--src DIR] [--dst DIR]

The bundle is loaded with the same checks the API uses (schemas, file hashes, queue and cases
agree) and refused if any fails. Default source: the snapshot folder from the settings
(RS_SNAPSHOT_DIR or data/snapshots). Default destination: frontend/public/snapshots.
"""

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ringsentinel.snapshots.bundle import BUNDLE_FILES, SnapshotError, load_bundle  # noqa: E402

DEFAULT_DST = ROOT / "frontend" / "public" / "snapshots"
CASES_WARN_BYTES = 5 * 1024 * 1024


def sync(src: Path, dst: Path) -> dict:
    """Validate `src` and copy its six files into `dst`. Returns the bundle meta."""
    bundle = load_bundle(src)  # raises SnapshotError on any problem; nothing is copied then
    dst.mkdir(parents=True, exist_ok=True)
    for name in BUNDLE_FILES:
        shutil.copyfile(Path(src) / name, dst / name)
    return bundle.meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, default=None)
    parser.add_argument("--dst", type=Path, default=DEFAULT_DST)
    args = parser.parse_args(argv)
    src = args.src
    if src is None:
        from ringsentinel.config import get_settings  # lazy: only needed for the default

        src = get_settings().snapshots_dir
    try:
        meta = sync(Path(src), args.dst)
    except SnapshotError as exc:
        print(f"SYNC REFUSED: {exc}")
        return 1
    size = (args.dst / "cases.json").stat().st_size
    print(f"bundle_id      {meta['bundle_id']}")
    print(f"copied to      {args.dst}")
    print(f"rings          {meta['n_rings_exported']} exported of {meta['n_rings_total']}")
    print(f"cases.json     {size / 1024:.0f} KiB")
    if size > CASES_WARN_BYTES:
        print(
            "WARNING: cases.json is large; the browser downloads all of it "
            "for the offline case view."
        )
    if not meta["evaluation_frozen"]:
        print("note: evaluation_frozen is false; do not commit this bundle as final numbers yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
