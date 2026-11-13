"""Read-only diagnosis of pattern-to-CSV matching (repo root, venv active).

    python scripts\\diagnose_matching.py

Reads the raw CSV and patterns file of the current variant, prints which field(s) disagree and
saves the text and JSON report next to the processed data. It changes no labels and no checks.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make the backend package importable when this script is run directly (not via pytest).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from ringsentinel.config import get_settings  # noqa: E402
from ringsentinel.ingest.diagnose import (
    diagnose_account_columns,
    diagnose_legs,
    diagnose_matching,
    format_account_columns,
    format_diagnosis,
    format_legs,
)  # noqa: E402
from ringsentinel.ingest.normalize import read_transactions  # noqa: E402
from ringsentinel.ingest.patterns import parse_patterns  # noqa: E402


def head_lines(path: Path, n: int = 4) -> list[str]:
    with path.open("r", encoding="utf-8") as handle:
        return [next(handle).rstrip("\n") for _ in range(n)]


def main() -> int:
    settings = get_settings()
    print(f"Variant: {settings.dataset_variant}")
    print(f"\nFirst lines of {settings.trans_path.name}:")
    for line in head_lines(settings.trans_path, 4):
        print(f"  {line}")
    print(f"\nFirst lines of {settings.patterns_path.name}:")
    for line in head_lines(settings.patterns_path, 4):
        print(f"  {line}")
    print("\nReading files (takes a minute)...")
    events = read_transactions(settings.trans_path)
    patterns = parse_patterns(settings.patterns_path)
    report = diagnose_matching(events, patterns)
    legs = diagnose_legs(events, patterns)
    report["legs"] = legs
    accounts = diagnose_account_columns(events, patterns)
    report["account_columns"] = accounts
    text = format_account_columns(accounts) + format_diagnosis(report) + format_legs(legs)
    print(text)
    out_dir = settings.processed_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "match_diagnosis.txt").write_text(text, encoding="utf-8")
    (out_dir / "match_diagnosis.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved {out_dir / 'match_diagnosis.txt'} and match_diagnosis.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
