"""Show giant-component size with and without hub control (repo root, venv active).

    python scripts\\ablation_giant_component.py
    python scripts\\ablation_giant_component.py --window val

Needs the noise layer: run  python scripts\\run_stage02.py --step noise  first. Writes
ablation_giant_component.json next to the other processed outputs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from ringsentinel.config import get_settings  # noqa: E402
from ringsentinel.stage02 import WINDOWS, format_ablation, run_ablation  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--window", choices=WINDOWS)
    args = parser.parse_args(argv)
    settings = get_settings()
    if not settings.noise_path.exists():
        print("Missing noise.parquet. Run: python scripts\\run_stage02.py --step noise")
        return 1
    result = run_ablation(settings, (args.window,) if args.window else WINDOWS)
    print(format_ablation(result))
    print(f"Saved: {settings.ablation_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
