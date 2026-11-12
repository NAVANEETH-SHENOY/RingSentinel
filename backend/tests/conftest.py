"""Shared fixtures: a small synthetic dataset in the real file layout (10-column CSV without a
label column, patterns file with BEGIN/END blocks and an 11th label field)."""

import random
from datetime import datetime, timedelta

import pytest

BASE = datetime(2022, 9, 1)
FORMATS = ["Cheque", "Credit Card", "ACH", "Cash", "Reinvestment", "Wire", "Bitcoin"]
CURRENCIES = ["US Dollar", "Euro", "Rupee", "Yen", "Bitcoin"]
TYPES = ["FAN-OUT", "FAN-IN", "CYCLE", "GATHER-SCATTER", "BIPARTITE", "STACK"]
HEADER = (
    "Timestamp,From Bank,Account,To Bank,Account,Amount Received,Receiving Currency,"
    "Amount Paid,Payment Currency,Payment Format\n"
)


def _stamp(minutes: int) -> str:
    return (BASE + timedelta(minutes=minutes)).strftime("%Y/%m/%d %H:%M")


def write_synthetic(raw_dir, n_legit=15000, n_blocks=12, seed=7):
    """Write HI-Small_Trans.csv and HI-Small_Patterns.txt into raw_dir; return facts."""
    rng = random.Random(seed)
    raw_dir.mkdir(parents=True, exist_ok=True)
    banks = ["010", "001", "0021", "03208", "012", "070"]
    accounts = sorted({f"80{rng.randrange(16**6):06X}" for _ in range(400)})[:300]
    accounts.append("812E34560")  # looks like a float in scientific notation; must stay a string

    rows: list[list[str]] = []
    for _ in range(n_legit):
        src, dst = rng.sample(accounts, 2)
        cur = rng.choice(CURRENCIES)
        amount = round(rng.lognormvariate(7, 1.2), 2)
        rows.append(
            [_stamp(rng.randrange(0, 10 * 1440)), rng.choice(banks), src, rng.choice(banks), dst,
             repr(amount), cur, repr(amount), cur, rng.choice(FORMATS)]
        )  # fmt: skip
    for _ in range(20):  # self-transfers
        acct = rng.choice(accounts)
        bank = rng.choice(banks)
        amount = round(rng.uniform(100, 5000), 2)
        rows.append(
            [_stamp(rng.randrange(0, 10 * 1440)), bank, acct, bank, acct,
             repr(amount), "US Dollar", repr(amount), "US Dollar", "Reinvestment"]
        )  # fmt: skip
    rows.append([_stamp(15 * 1440), "010", accounts[0], "001", accounts[1], "5.5", "Euro", "5.5",
                 "Euro", "Wire"])  # fmt: skip  (a late straggler, like the real file's day-18 rows)

    pattern_lines: list[str] = []
    n_pattern_lines = 0
    first_block_row = None
    for b in range(n_blocks):
        kind = TYPES[b % len(TYPES)]
        start = int((b / n_blocks) * 9 * 1440) + rng.randrange(0, 300)
        chain = rng.sample(accounts, rng.randrange(7, 10))
        pattern_lines.append(f"BEGIN LAUNDERING ATTEMPT - {kind}:  Max 2 hops")
        minute = start
        for a, c in zip(chain, chain[1:], strict=False):
            minute += rng.randrange(5, 120)
            cur = rng.choice(CURRENCIES)
            amount = round(rng.uniform(5000, 900000), 2)
            bank_a, bank_c = rng.choice(banks), rng.choice(banks)
            stamp = _stamp(minute)
            rows.append([stamp, bank_a, a, bank_c, c, repr(amount), cur, repr(amount), cur, "ACH"])
            if first_block_row is None:
                first_block_row = rows[-1]
            pattern_lines.append(
                f"{stamp},{bank_a},{a},{bank_c},{c},{amount:.2f},{cur},{amount:.2f},{cur},ACH,1"
            )
            n_pattern_lines += 1
        pattern_lines.append(f"END LAUNDERING ATTEMPT - {kind}")
        pattern_lines.append("")
    rows.append(list(first_block_row))  # identical duplicate of a laundering row (stays unlabelled)

    rng.shuffle(rows)
    trans_path = raw_dir / "HI-Small_Trans.csv"
    trans_path.write_text(HEADER + "\n".join(",".join(r) for r in rows) + "\n", encoding="utf-8")
    patterns_path = raw_dir / "HI-Small_Patterns.txt"
    patterns_path.write_text("\n".join(pattern_lines) + "\n", encoding="utf-8")
    return {
        "trans_path": trans_path,
        "patterns_path": patterns_path,
        "n_rows": len(rows),
        "n_pattern_lines": n_pattern_lines,
        "n_blocks": n_blocks,
        "accounts": accounts,
    }


@pytest.fixture
def synthetic(tmp_path):
    info = write_synthetic(tmp_path / "data" / "raw")
    info["data_dir"] = tmp_path / "data"
    return info
