r"""Run the API locally.  Usage (repo root, cmd):  python scripts\run_api.py [--port 8000]"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    import uvicorn
    from app.main import create_app
    from ringsentinel.snapshots.bundle import SnapshotError

    try:
        app = create_app()
    except SnapshotError as exc:
        print(f"CANNOT START: {exc}")
        return 1
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
