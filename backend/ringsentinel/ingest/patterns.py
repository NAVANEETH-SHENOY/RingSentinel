"""Parse the patterns file (laundering attempts) into a table with one row per transaction.

Layout observed in the owner's HI-Small_Patterns.txt:

    BEGIN LAUNDERING ATTEMPT - <TYPE>[:  <detail>]
    <11 comma-separated fields: the 10 transaction fields, then a 1/0 label>
    ...
    END LAUNDERING ATTEMPT - <TYPE>

Each BEGIN/END block is one ring; ring_id is its 1-based position in the file.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from ringsentinel.ingest.schema import INTERNAL_NAMES, TIMESTAMP_FORMAT

BEGIN_RE = re.compile(r"^BEGIN LAUNDERING ATTEMPT - (?P<type>[A-Z][A-Z-]*)(?::\s*(?P<detail>.*))?$")
END_RE = re.compile(r"^END LAUNDERING ATTEMPT - (?P<type>[A-Z][A-Z-]*)\s*$")
EXPECTED_FIELDS = len(INTERNAL_NAMES) + 1  # 10 transaction fields + label

PATTERN_COLUMNS = [
    "line_no",
    "ring_id",
    "ring_type",
    "ring_detail",
    *INTERNAL_NAMES,
    "pattern_label",
]


class PatternError(ValueError):
    """The patterns file does not follow the expected layout."""


def parse_patterns(path: Path) -> pd.DataFrame:
    records: list[list] = []
    ring_id = 0
    current_type: str | None = None
    current_detail = ""
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            begin = BEGIN_RE.match(line)
            if begin:
                if current_type is not None:
                    raise PatternError(f"line {line_no}: BEGIN inside an open block")
                ring_id += 1
                current_type = begin.group("type")
                current_detail = (begin.group("detail") or "").strip()
                continue
            end = END_RE.match(line)
            if end:
                if current_type is None:
                    raise PatternError(f"line {line_no}: END without BEGIN")
                if end.group("type") != current_type:
                    raise PatternError(
                        f"line {line_no}: END {end.group('type')} closes BEGIN {current_type}"
                    )
                current_type = None
                continue
            if not line[0].isdigit():
                raise PatternError(f"line {line_no}: unrecognised line {line!r}")
            if current_type is None:
                raise PatternError(f"line {line_no}: transaction outside a BEGIN/END block")
            fields = line.split(",")
            if len(fields) != EXPECTED_FIELDS:
                raise PatternError(
                    f"line {line_no}: expected {EXPECTED_FIELDS} fields, found {len(fields)}"
                )
            ts, sb, sa, db, da, a_recv, c_recv, a_paid, c_paid, fmt, label = fields
            records.append(
                [line_no, ring_id, current_type, current_detail, ts, sb, sa, db, da,
                 float(a_recv), c_recv, float(a_paid), c_paid, fmt, int(label)]
            )  # fmt: skip
    if current_type is not None:
        raise PatternError(f"file ends inside an open {current_type} block")
    frame = pd.DataFrame(records, columns=PATTERN_COLUMNS)
    frame["ts"] = pd.to_datetime(frame["ts"], format=TIMESTAMP_FORMAT)
    return frame
