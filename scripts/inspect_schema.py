"""Print the real schema of a raw transactions CSV and its patterns file. Standard library only.

It assumes nothing about column names. Output is meant to be pasted back into the chat so the
ingestor can be written against facts, not guesses.

Usage (from the repo root):
    python scripts/inspect_schema.py --trans data/raw/<transactions>.csv
        --patterns data/raw/<patterns>.txt

Both arguments are optional; give whichever files you have. The report is printed and also
saved to data/raw/schema_report.txt (that folder is gitignored).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from collections import Counter
from pathlib import Path

MAX_DISTINCT = 50
SAMPLE_ROWS = 5
PATTERN_HEAD_LINES = 40
PATTERN_TOP_N = 25


def sha256_of(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def _to_float(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


class _ColumnStats:
    """Streaming stats for one column, tracked by position (names can repeat)."""

    def __init__(self, name: str, position: int) -> None:
        self.name = name
        self.position = position
        self.empty = 0
        self.distinct: Counter[str] = Counter()
        self.overflow = False
        self.numeric_count = 0
        self.num_min: float | None = None
        self.num_max: float | None = None
        self.str_min: str | None = None
        self.str_max: str | None = None

    def add(self, value: str) -> None:
        if value == "":
            self.empty += 1
            return
        if self.str_min is None or value < self.str_min:
            self.str_min = value
        if self.str_max is None or value > self.str_max:
            self.str_max = value
        number = _to_float(value)
        if number is not None:
            self.numeric_count += 1
            self.num_min = number if self.num_min is None else min(self.num_min, number)
            self.num_max = number if self.num_max is None else max(self.num_max, number)
        if not self.overflow:
            self.distinct[value] += 1
            if len(self.distinct) > MAX_DISTINCT:
                self.overflow = True
                self.distinct.clear()

    def summary(self) -> dict:
        return {
            "position": self.position,
            "name": self.name,
            "empty": self.empty,
            "numeric_count": self.numeric_count,
            "num_min": self.num_min,
            "num_max": self.num_max,
            "str_min": self.str_min,
            "str_max": self.str_max,
            "distinct_capped": self.overflow,
            "distinct_values": None if self.overflow else dict(self.distinct.most_common()),
        }


def inspect_csv(path: Path, progress_every: int = 0) -> dict:
    """Stream the CSV once and collect schema facts."""
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        columns = [_ColumnStats(name, i) for i, name in enumerate(header)]
        samples: list[list[str]] = []
        rows = 0
        ragged = 0
        first_col_sorted = True
        previous_first: str | None = None
        first_value: str | None = None
        last_value: str | None = None
        for row in reader:
            rows += 1
            if len(row) != len(header):
                ragged += 1
            if len(samples) < SAMPLE_ROWS:
                samples.append(row)
            for column, value in zip(columns, row, strict=False):
                column.add(value)
            if row:
                current = row[0]
                if first_value is None:
                    first_value = current
                if previous_first is not None and current < previous_first:
                    first_col_sorted = False
                previous_first = current
                last_value = current
            if progress_every and rows % progress_every == 0:
                print(f"  ...{rows:,} rows read", file=sys.stderr)
    names = [c.name for c in columns]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_of(path),
        "header": header,
        "duplicate_header_names": duplicates,
        "row_count": rows,
        "ragged_rows": ragged,
        "first_column_first_value": first_value,
        "first_column_last_value": last_value,
        "first_column_sorted_ascending_as_text": first_col_sorted,
        "columns": [c.summary() for c in columns],
        "sample_rows": samples,
    }


def inspect_patterns(path: Path) -> dict:
    """Describe a patterns text file without assuming its layout."""
    head: list[str] = []
    total = 0
    data_like = 0
    other_lines: Counter[str] = Counter()
    other_prefix: Counter[str] = Counter()
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.rstrip("\r\n")
            total += 1
            if len(head) < PATTERN_HEAD_LINES:
                head.append(line)
            stripped = line.strip()
            if not stripped:
                continue
            if stripped[0].isdigit():
                data_like += 1
            else:
                other_lines[stripped] += 1
                other_prefix[" ".join(stripped.split()[:2])] += 1
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_of(path),
        "total_lines": total,
        "lines_starting_with_digit": data_like,
        "other_line_count": sum(other_lines.values()),
        "other_line_top": other_lines.most_common(PATTERN_TOP_N),
        "other_prefix_top": other_prefix.most_common(PATTERN_TOP_N),
        "head": head,
    }


def format_report(trans: dict | None, patterns: dict | None) -> str:
    lines: list[str] = ["=== SCHEMA REPORT ==="]
    if trans:
        lines += [
            "",
            f"[transactions] {trans['path']}",
            f"size_bytes={trans['size_bytes']}  sha256={trans['sha256']}",
            f"rows={trans['row_count']}  ragged_rows={trans['ragged_rows']}",
            f"header={trans['header']}",
            f"duplicate_header_names={trans['duplicate_header_names']}",
            f"first_column: first={trans['first_column_first_value']!r} "
            f"last={trans['first_column_last_value']!r} "
            f"sorted_ascending_as_text={trans['first_column_sorted_ascending_as_text']}",
            "",
            "columns (by position):",
        ]
        for col in trans["columns"]:
            lines.append(
                f"  #{col['position']} {col['name']!r}: empty={col['empty']} "
                f"numeric={col['numeric_count']} num_range=({col['num_min']}, {col['num_max']}) "
                f"text_range=({col['str_min']!r}, {col['str_max']!r})"
            )
            if col["distinct_capped"]:
                lines.append(f"      distinct values: more than {MAX_DISTINCT}")
            else:
                lines.append(f"      distinct values: {col['distinct_values']}")
        lines += ["", "first rows:"]
        lines += [f"  {row}" for row in trans["sample_rows"]]
    if patterns:
        lines += [
            "",
            f"[patterns] {patterns['path']}",
            f"size_bytes={patterns['size_bytes']}  sha256={patterns['sha256']}",
            f"total_lines={patterns['total_lines']}  "
            f"lines_starting_with_digit={patterns['lines_starting_with_digit']}  "
            f"other_lines={patterns['other_line_count']}",
            "most common non-digit lines:",
        ]
        lines += [f"  {count:>7}  {text}" for text, count in patterns["other_line_top"]]
        lines.append("most common non-digit line prefixes (first two words):")
        lines += [f"  {count:>7}  {text}" for text, count in patterns["other_prefix_top"]]
        lines.append(f"first {len(patterns['head'])} lines:")
        lines += [f"  {text}" for text in patterns["head"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--trans", type=Path, help="transactions CSV")
    parser.add_argument("--patterns", type=Path, help="patterns text file")
    parser.add_argument(
        "--out", type=Path, default=Path("data/raw/schema_report.txt"), help="report path"
    )
    args = parser.parse_args(argv)
    if not args.trans and not args.patterns:
        parser.error("give --trans and/or --patterns")
    for given in (args.trans, args.patterns):
        if given and not given.is_file():
            print(f"File not found: {given}", file=sys.stderr)
            return 2
    trans = inspect_csv(args.trans, progress_every=1_000_000) if args.trans else None
    patterns = inspect_patterns(args.patterns) if args.patterns else None
    report = format_report(trans, patterns)
    print(report)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print(f"(saved to {args.out})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
