r"""Stage 06: build the AI layer's case files and merge them into the snapshot bundle.

Usage (repo root, cmd):
  python scripts\run_stage06.py                       offline template for every case
  python scripts\run_stage06.py --provider fake       demo run, no key, NOT a real model
  python scripts\run_stage06.py --provider groq --limit 20
  python scripts\run_stage06.py --provider gemini --all

Needs the bundle from scripts\export_snapshots.py. Verified model output is cached, so a stopped
or repeated run continues where it left off and costs no new requests for finished cases.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ringsentinel.ai.provider import ProviderError  # noqa: E402
from ringsentinel.config import get_settings  # noqa: E402
from ringsentinel.snapshots.bundle import SnapshotError  # noqa: E402
from ringsentinel.stage06 import format_report, run_ai  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--provider", choices=("none", "fake", "groq", "gemini"), default=None,
                        help="default: RS_LLM_PROVIDER, else none")  # fmt: skip
    parser.add_argument(
        "--model", default=None, help="default: RS_LLM_MODEL or the provider default"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--limit", type=int, default=None,
        help="how many top-ranked cases may use the model (default: RS_AI_MAX_LLM_CASES)",
    )  # fmt: skip
    group.add_argument("--all", action="store_true", help="let every case use the model")
    parser.add_argument(
        "--refresh", action="store_true",
        help="ignore the cache (it is still used if the provider fails)",
    )  # fmt: skip
    parser.add_argument(
        "--no-apply", action="store_true",
        help="write ai_cases.json only; do not touch the bundle",
    )  # fmt: skip
    parser.add_argument(
        "--snapshots", type=Path, default=None, help="bundle folder (default: data/snapshots)"
    )
    args = parser.parse_args(argv)
    settings = get_settings()

    def progress(done: int, total: int, ring_id: str) -> None:
        if done % 10 == 0 or done == total:
            print(f"  {done}/{total} cases done (last: {ring_id})", flush=True)

    limit = None if args.all else (-1 if args.limit is None else args.limit)
    try:
        report = run_ai(
            settings, provider_name=args.provider, model=args.model, limit=limit,
            refresh=args.refresh, apply=not args.no_apply, snapshots_dir=args.snapshots,
            progress=progress,
        )  # fmt: skip
    except (ProviderError, SnapshotError) as exc:
        print(f"STAGE 06 FAILED: {exc}")
        return 1
    except KeyboardInterrupt:
        print("Interrupted. Verified case files are cached; run the same command to continue.")
        return 130
    print(format_report(report))
    print(f"\nwritten: {settings.ai_cases_path}\n         {settings.ai_report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
