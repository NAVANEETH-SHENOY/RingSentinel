"""The raw file layout, as observed in the owner's HI-Small_Trans.csv schema report.

The raw header repeats the name 'Account' (once for the sender, once for the receiver), so
columns are always handled by position and renamed to the internal names below.
"""

from __future__ import annotations

# First ten columns of HI-Small_Trans.csv as reported by scripts/inspect_schema.py.
RAW_COLUMNS: tuple[str, ...] = (
    "Timestamp",
    "From Bank",
    "Account",
    "To Bank",
    "Account",
    "Amount Received",
    "Receiving Currency",
    "Amount Paid",
    "Payment Currency",
    "Payment Format",
)

# 11th column. Present in the corrected HI-Small download (the label source); an earlier
# download lacked it, so a 10-column file is still accepted.
LABEL_COLUMN = "Is Laundering"

INTERNAL_NAMES: tuple[str, ...] = (
    "ts",
    "src_bank",
    "src_account",
    "dst_bank",
    "dst_account",
    "amount_received",
    "recv_currency",
    "amount_paid",
    "pay_currency",
    "payment_format",
)

TIMESTAMP_FORMAT = "%Y/%m/%d %H:%M"

# Columns that identify one transaction; used to match pattern lines to CSV rows.
KEY_COLUMNS: tuple[str, ...] = INTERNAL_NAMES
STRING_KEY_COLUMNS: tuple[str, ...] = (
    "src_bank",
    "src_account",
    "dst_bank",
    "dst_account",
    "recv_currency",
    "pay_currency",
    "payment_format",
)


class SchemaError(ValueError):
    """The raw file does not look like the layout this code was written for."""


def check_header(header: list[str]) -> bool:
    """Validate the CSV header. Returns True if the optional label column is present."""
    cols = tuple(header)
    if cols == RAW_COLUMNS:
        return False
    if cols == (*RAW_COLUMNS, LABEL_COLUMN):
        return True
    raise SchemaError(
        "Unexpected transactions header.\n"
        f"  expected: {list(RAW_COLUMNS)} (optionally followed by {LABEL_COLUMN!r})\n"
        f"  found:    {header}\n"
        "Re-run scripts/inspect_schema.py and compare."
    )
