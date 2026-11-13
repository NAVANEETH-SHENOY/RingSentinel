"""Read-only diagnostic for pattern-to-CSV matching failures.

It answers one question with data: when pattern lines do not match CSV rows, WHICH field
disagrees? It never changes labels, never relaxes a check and never writes to the event table.

Method (every number below is computed from the two files, nothing is assumed):
  1. Progressive match levels: how many pattern lines have a CSV row agreeing on ts, then
     ts+src_account, and so on up to all ten fields.
  2. Leave-one-field-out: all ten fields except one. The field whose removal lifts the match
     count is the field that disagrees.
  3. Value presence: for each field, how many pattern values exist anywhere in the CSV column.
  4. Vocabulary: currencies, formats and banks that appear in only one of the two files.
  5. Nearest row: for each pattern line, the CSV row between the same two accounts that is
     closest in time, and per-field agreement with it (plus the time offset and amount ratio).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ringsentinel.ingest.schema import KEY_COLUMNS, STRING_KEY_COLUMNS

PROGRESSIVE: list[tuple[str, list[str]]] = [
    ("ts", ["ts"]),
    ("ts+src_account", ["ts", "src_account"]),
    ("ts+src_account+dst_account", ["ts", "src_account", "dst_account"]),
    (
        "+banks",
        ["ts", "src_account", "dst_account", "src_bank", "dst_bank"],
    ),
    (
        "+amounts",
        [
            "ts",
            "src_account",
            "dst_account",
            "src_bank",
            "dst_bank",
            "amount_paid",
            "amount_received",
        ],
    ),
    (
        "+currencies",
        [
            "ts",
            "src_account",
            "dst_account",
            "src_bank",
            "dst_bank",
            "amount_paid",
            "amount_received",
            "recv_currency",
            "pay_currency",
        ],
    ),
    ("all_10_fields", list(KEY_COLUMNS)),
]
PAIR_LEVELS: list[tuple[str, list[str]]] = [
    ("src_account+dst_account (any time)", ["src_account", "dst_account"]),
    ("src_account+dst_account+amount_paid", ["src_account", "dst_account", "amount_paid"]),
]
VOCAB_COLUMNS = ("src_bank", "dst_bank", "recv_currency", "pay_currency", "payment_format")


def _stringify(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in STRING_KEY_COLUMNS:
        if col in out.columns:
            out[col] = out[col].astype(str)
    return out


def _count_matches(pats: pd.DataFrame, cand: pd.DataFrame, keys: list[str]) -> int:
    right = cand[keys].drop_duplicates()
    merged = pats[["line_no", *keys]].merge(right, on=keys, how="left", indicator=True)
    return int((merged["_merge"] == "both").sum())


def _unique_strings(series: pd.Series) -> set[str]:
    if isinstance(series.dtype, pd.CategoricalDtype):
        return set(series.cat.remove_unused_categories().cat.categories.astype(str))
    return set(series.astype(str).unique())


def _nearest_by(pats: pd.DataFrame, cand: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """For each pattern line, the CSV row sharing `keys` that is closest in time."""
    cols = [c for c in KEY_COLUMNS if c not in keys]
    right = cand[["event_id", *keys, *cols]].rename(columns={c: f"csv_{c}" for c in cols})
    merged = pats[["line_no", *keys, *cols]].merge(right, on=keys, how="inner")
    if merged.empty:
        return merged
    merged["abs_dt"] = (merged["csv_ts"] - merged["ts"]).abs() if "ts" in cols else 0
    merged = merged.sort_values(["line_no", "abs_dt"]).drop_duplicates("line_no")
    return merged


def _agreement(nearest: pd.DataFrame, keys: list[str]) -> dict[str, float]:
    out: dict[str, float] = {k: 1.0 for k in keys}
    for col in KEY_COLUMNS:
        if col in keys or f"csv_{col}" not in nearest.columns:
            continue
        out[col] = float((nearest[col] == nearest[f"csv_{col}"]).mean())
    return out


def _nearest_report(pats: pd.DataFrame, cand: pd.DataFrame, keys: list[str], n_lines: int) -> dict:
    nearest = _nearest_by(pats, cand, keys)
    report: dict = {"keys": keys, "lines_with_candidate": int(len(nearest))}
    report["fraction_of_pattern_lines"] = len(nearest) / max(n_lines, 1)
    if nearest.empty:
        return report
    report["field_agreement_with_nearest_row"] = _agreement(nearest, keys)
    if "ts" not in keys:
        delta = ((nearest["csv_ts"] - nearest["ts"]).dt.total_seconds() / 60.0).round(0)
        top = delta.value_counts().head(10)
        report["time_offset_minutes_top10"] = {str(int(k)): int(v) for k, v in top.items()}
        report["time_offset_minutes_quantiles"] = {
            str(q): float(delta.quantile(q)) for q in (0.05, 0.25, 0.5, 0.75, 0.95)
        }
    if "amount_paid" not in keys:
        ratio = nearest["csv_amount_paid"] / nearest["amount_paid"].replace(0.0, np.nan)
        ratio = ratio.replace([np.inf, -np.inf], np.nan).dropna()
        if len(ratio):
            report["amount_paid_ratio_csv_over_pattern"] = {
                str(q): float(ratio.quantile(q)) for q in (0.05, 0.25, 0.5, 0.75, 0.95)
            }
    return report


def diagnose_matching(events: pd.DataFrame, patterns: pd.DataFrame, max_examples: int = 5) -> dict:
    """Return a JSON-friendly report on why pattern lines do or do not match CSV rows.

    `events` is the table from read_transactions; `patterns` is from parse_patterns.
    """
    n_lines = int(len(patterns))
    pats = _stringify(patterns[["line_no", "ring_id", "ring_type", *KEY_COLUMNS]])
    report: dict = {
        "n_csv_rows": int(len(events)),
        "n_pattern_lines": n_lines,
        "pattern_lines_exact_duplicates": int(pats.duplicated(list(KEY_COLUMNS)).sum()),
    }

    report["ranges"] = {
        "csv_ts": [str(events["ts"].min()), str(events["ts"].max())],
        "pattern_ts": [str(pats["ts"].min()), str(pats["ts"].max())],
        "csv_amount_paid": [float(events["amount_paid"].min()), float(events["amount_paid"].max())],
        "pattern_amount_paid": [float(pats["amount_paid"].min()), float(pats["amount_paid"].max())],
    }

    # 3. value presence per field
    presence: dict[str, float] = {}
    for col in KEY_COLUMNS:
        if col in STRING_KEY_COLUMNS:
            known = _unique_strings(events[col])
            presence[col] = float(pats[col].isin(known).mean())
        else:
            presence[col] = float(pats[col].isin(events[col].unique()).mean())
    report["pattern_value_present_in_csv_column"] = presence

    # 4. vocabulary differences
    vocab: dict[str, dict] = {}
    for col in VOCAB_COLUMNS:
        csv_vals = _unique_strings(events[col])
        pat_vals = set(pats[col].unique())
        vocab[col] = {
            "csv_distinct": len(csv_vals),
            "pattern_distinct": len(pat_vals),
            "only_in_patterns": sorted(pat_vals - csv_vals)[:15],
            "only_in_csv_sample": sorted(csv_vals - pat_vals)[:15],
        }
    report["vocabulary"] = vocab

    # Candidate rows: any CSV row sharing ts, an account or the paid amount with some pattern
    # line. Exact for every ts-level/leave-one-out match below (each keeps at least 3 of these 4).
    mask = (
        events["ts"].isin(pats["ts"].unique())
        | events["src_account"].isin(pats["src_account"].unique())
        | events["dst_account"].isin(pats["dst_account"].unique())
        | events["amount_paid"].isin(pats["amount_paid"].unique())
    )
    cand = _stringify(events.loc[mask, ["event_id", *KEY_COLUMNS]])
    report["candidate_csv_rows"] = int(len(cand))

    # 1. progressive levels
    report["progressive_match_lines"] = {
        name: _count_matches(pats, cand, keys) for name, keys in PROGRESSIVE
    }
    # 2. leave-one-out
    report["leave_one_field_out_match_lines"] = {
        f"without_{col}": _count_matches(pats, cand, [k for k in KEY_COLUMNS if k != col])
        for col in KEY_COLUMNS
    }
    # account-pair levels (these need candidates that share accounts, which the mask covers)
    report["account_pair_levels"] = {
        name: _count_matches(pats, cand, keys) for name, keys in PAIR_LEVELS
    }

    # same occurrence logic as attach_labels, for a like-for-like number
    c2 = cand.sort_values("event_id").copy()
    c2["occ"] = c2.groupby(list(KEY_COLUMNS), sort=False).cumcount()
    p2 = pats.copy()
    p2["occ"] = p2.groupby(list(KEY_COLUMNS), sort=False).cumcount()
    occ = p2.merge(c2[["event_id", "occ", *KEY_COLUMNS]], on=[*KEY_COLUMNS, "occ"], how="left")
    report["matched_with_occurrence_logic"] = int(occ["event_id"].notna().sum())

    # 5. nearest row
    report["nearest_by_account_pair"] = _nearest_report(
        pats, cand, ["src_account", "dst_account"], n_lines
    )
    report["nearest_by_src_account"] = _nearest_report(pats, cand, ["src_account"], n_lines)

    # examples: first unmatched lines with their nearest same-pair row
    nearest = _nearest_by(pats, cand, ["src_account", "dst_account"])
    matched_lines = set(occ.loc[occ["event_id"].notna(), "line_no"])
    examples = []
    for line_no in pats["line_no"]:
        if line_no in matched_lines:
            continue
        row = pats.loc[pats["line_no"] == line_no].iloc[0]
        example: dict = {
            "line_no": int(line_no),
            "pattern": {c: _plain(row[c]) for c in KEY_COLUMNS},
        }
        near = nearest.loc[nearest["line_no"] == line_no]
        if len(near):
            r = near.iloc[0]
            example["nearest_csv_row"] = {
                c: _plain(r[f"csv_{c}"] if f"csv_{c}" in near.columns else r[c])
                for c in KEY_COLUMNS
            }
            example["fields_that_differ"] = [
                c for c in KEY_COLUMNS if f"csv_{c}" in near.columns and r[c] != r[f"csv_{c}"]
            ]
        else:
            example["nearest_csv_row"] = None
        examples.append(example)
        if len(examples) >= max_examples:
            break
    report["unmatched_examples"] = examples
    return report


LEG_ANCHOR = ["ts", "amount_received", "recv_currency"]
LEG_CLASSES = (
    "exact_row_exists",
    "endpoints_in_one_row_other_fields_differ",
    "stitched_src_from_one_row_dst_from_another",
    "endpoints_swapped_in_csv",
    "src_endpoint_only",
    "dst_endpoint_only",
    "anchor_rows_but_no_endpoint_match",
    "no_anchor_row",
)


def _rate(mask: pd.Series) -> float:
    return float(mask.mean()) if len(mask) else float("nan")


def diagnose_legs(events: pd.DataFrame, patterns: pd.DataFrame, max_examples: int = 5) -> dict:
    """Classify every pattern line by how its endpoints relate to CSV rows at the same moment.

    A pattern line is LOCATED (not matched) through ts + amount_received + recv_currency. These
    three fields are only used to find candidate rows so that the endpoint fields can be compared;
    nothing here assigns a label. Classes (first that applies):
      exact_row_exists                 a located row agrees on all ten fields
      endpoints_in_one_row_...         one row has both endpoints, but another field differs
      stitched_...                     the sender is the sender of one row, the receiver is the
                                       receiver of a DIFFERENT located row
      endpoints_swapped_in_csv         sender/receiver appear reversed
      src_endpoint_only / dst_endpoint_only
      anchor_rows_but_no_endpoint_match
      no_anchor_row                    no CSV row has this ts and amount_received
    For stitched lines it also reports how the two rows relate, to derive the mapping from many
    examples instead of one.
    """
    pats = _stringify(patterns[["line_no", *KEY_COLUMNS]])
    n_lines = int(len(pats))
    mask = events["ts"].isin(pats["ts"].unique()) & events["amount_received"].isin(
        pats["amount_received"].unique()
    )
    rows = _stringify(events.loc[mask, ["event_id", *KEY_COLUMNS]])
    report: dict = {
        "n_pattern_lines": n_lines,
        "rows_at_same_ts_and_amount_received": int(len(rows)),
    }

    loose = pats.merge(rows[["ts", "amount_received"]].drop_duplicates(), how="inner",
                       on=["ts", "amount_received"])  # fmt: skip
    report["lines_with_row_at_same_ts_and_amount_received_any_currency"] = int(
        loose["line_no"].nunique()
    )

    renamed = rows.rename(columns={c: f"r_{c}" for c in KEY_COLUMNS if c not in LEG_ANCHOR}).rename(
        columns={"event_id": "r_event_id"}
    )
    pairs = pats.merge(renamed, on=LEG_ANCHOR, how="inner")
    report["lines_with_anchor_row"] = int(pairs["line_no"].nunique())

    pairs["src_as_src"] = (pairs["src_bank"] == pairs["r_src_bank"]) & (
        pairs["src_account"] == pairs["r_src_account"]
    )
    pairs["dst_as_dst"] = (pairs["dst_bank"] == pairs["r_dst_bank"]) & (
        pairs["dst_account"] == pairs["r_dst_account"]
    )
    pairs["src_as_dst"] = (pairs["src_bank"] == pairs["r_dst_bank"]) & (
        pairs["src_account"] == pairs["r_dst_account"]
    )
    pairs["dst_as_src"] = (pairs["dst_bank"] == pairs["r_src_bank"]) & (
        pairs["dst_account"] == pairs["r_src_account"]
    )
    pairs["rest_same"] = (
        (pairs["amount_paid"] == pairs["r_amount_paid"])
        & (pairs["pay_currency"] == pairs["r_pay_currency"])
        & (pairs["payment_format"] == pairs["r_payment_format"])
    )
    pairs["exact"] = pairs["src_as_src"] & pairs["dst_as_dst"] & pairs["rest_same"]
    pairs["both"] = pairs["src_as_src"] & pairs["dst_as_dst"]
    pairs["swapped"] = pairs["src_as_dst"] & pairs["dst_as_src"]
    flags = ["exact", "both", "swapped", "src_as_src", "dst_as_dst"]
    per_line = pairs.groupby("line_no")[flags].any().reindex(pats["line_no"], fill_value=False)
    has_anchor = pats["line_no"].isin(pairs["line_no"]).to_numpy()
    stitched = (
        per_line["src_as_src"].to_numpy()
        & per_line["dst_as_dst"].to_numpy()
        & ~per_line["both"].to_numpy()
    )
    conditions = [
        per_line["exact"].to_numpy(),
        per_line["both"].to_numpy(),
        stitched,
        per_line["swapped"].to_numpy(),
        per_line["src_as_src"].to_numpy(),
        per_line["dst_as_dst"].to_numpy(),
        has_anchor,
    ]
    label = np.select(conditions, LEG_CLASSES[:-1], default=LEG_CLASSES[-1])
    classes = pd.Series(label, index=per_line.index)
    report["classes"] = {name: int((classes == name).sum()) for name in LEG_CLASSES}

    cols = ["line_no", "r_event_id", "r_src_bank", "r_src_account", "r_dst_bank",
            "r_dst_account", "r_amount_paid", "r_pay_currency", "r_payment_format"]  # fmt: skip
    a_rows = pairs.loc[pairs["src_as_src"], cols].sort_values("r_event_id")
    b_rows = pairs.loc[pairs["dst_as_dst"], cols].sort_values("r_event_id")
    st_lines = set(classes.index[classes == "stitched_src_from_one_row_dst_from_another"])
    a_rows = a_rows[a_rows["line_no"].isin(st_lines)]
    b_rows = b_rows[b_rows["line_no"].isin(st_lines)]
    ambiguous = int(
        (a_rows.groupby("line_no").size() > 1).sum() + (b_rows.groupby("line_no").size() > 1).sum()
    )
    a_one = (
        a_rows.drop_duplicates("line_no").add_suffix("_A").rename(columns={"line_no_A": "line_no"})
    )
    b_one = (
        b_rows.drop_duplicates("line_no").add_suffix("_B").rename(columns={"line_no_B": "line_no"})
    )
    st = pats.merge(a_one, on="line_no").merge(b_one, on="line_no")
    detail: dict = {"n_lines": int(len(st)), "lines_with_more_than_one_candidate_row": ambiguous}
    if len(st):
        detail.update(
            {
                "row_A_is_self_transfer": _rate(st["r_src_account_A"] == st["r_dst_account_A"]),
                "row_B_is_self_transfer": _rate(st["r_src_account_B"] == st["r_dst_account_B"]),
                "row_A_same_bank_both_sides": _rate(st["r_src_bank_A"] == st["r_dst_bank_A"]),
                "row_B_same_bank_both_sides": _rate(st["r_src_bank_B"] == st["r_dst_bank_B"]),
                "row_A_pay_currency_differs_from_recv_currency": _rate(
                    st["r_pay_currency_A"] != st["recv_currency"]
                ),
                "pattern_paid_fields_equal_row_B": _rate(
                    (st["amount_paid"] == st["r_amount_paid_B"])
                    & (st["pay_currency"] == st["r_pay_currency_B"])
                    & (st["payment_format"] == st["r_payment_format_B"])
                ),
                "pattern_paid_fields_equal_row_A": _rate(
                    (st["amount_paid"] == st["r_amount_paid_A"])
                    & (st["pay_currency"] == st["r_pay_currency_A"])
                    & (st["payment_format"] == st["r_payment_format_A"])
                ),
                "A_ordered_before_B_in_file": _rate(st["r_event_id_A"] < st["r_event_id_B"]),
            }
        )
    report["stitched_detail"] = detail

    examples = []
    for _, row in st.head(max_examples).iterrows():
        examples.append(
            {
                "line_no": int(row["line_no"]),
                "pattern": {c: _plain(row[c]) for c in KEY_COLUMNS},
                "row_A_supplies_sender": {
                    "bank_from": row["r_src_bank_A"],
                    "account_from": row["r_src_account_A"],
                    "bank_to": row["r_dst_bank_A"],
                    "account_to": row["r_dst_account_A"],
                    "paid": [_plain(row["r_amount_paid_A"]), row["r_pay_currency_A"]],
                    "format": row["r_payment_format_A"],
                },
                "row_B_supplies_receiver": {
                    "bank_from": row["r_src_bank_B"],
                    "account_from": row["r_src_account_B"],
                    "bank_to": row["r_dst_bank_B"],
                    "account_to": row["r_dst_account_B"],
                    "paid": [_plain(row["r_amount_paid_B"]), row["r_pay_currency_B"]],
                    "format": row["r_payment_format_B"],
                },
            }
        )
    report["stitched_examples"] = examples
    return report


def format_legs(report: dict) -> str:
    """Human-readable text for the report from diagnose_legs."""
    n = report["n_pattern_lines"]
    lines = [
        "",
        "Endpoint (leg) analysis: how pattern endpoints relate to CSV rows at the same moment",
        f"  CSV rows at a pattern ts and amount_received: "
        f"{report['rows_at_same_ts_and_amount_received']:,}",
        f"  lines with a row at the same ts and amount_received (any currency): "
        f"{report['lines_with_row_at_same_ts_and_amount_received_any_currency']:,}",
        f"  lines located through ts + amount_received + recv_currency: "
        f"{report['lines_with_anchor_row']:,}",
        "  classes:",
    ]
    for name, count in report["classes"].items():
        lines.append(f"    {name:<46} {count:>8,}  ({count / max(n, 1):.1%})")
    lines.append("  stitched lines, how the two rows relate:")
    for key, val in report["stitched_detail"].items():
        lines.append(f"    {key}: {val}")
    for ex in report["stitched_examples"]:
        lines.append(f"  example line {ex['line_no']}: pattern {ex['pattern']}")
        lines.append(f"      row A (sender): {ex['row_A_supplies_sender']}")
        lines.append(f"      row B (receiver): {ex['row_B_supplies_receiver']}")
    return "\n".join(lines) + "\n"


def diagnose_account_columns(events: pd.DataFrame, patterns: pd.DataFrame) -> dict:
    """Test whether the CSV's sender account column is an independent column.

    Reports how often sender equals receiver (overall, by payment format, and in the patterns
    file for comparison) and whether the two columns hold the same set of values.
    """
    same = events["src_account"] == events["dst_account"]
    src_set = set(events["src_account"].cat.remove_unused_categories().cat.categories)
    dst_set = set(events["dst_account"].cat.remove_unused_categories().cat.categories)
    by_format = same.groupby(events["payment_format"], observed=True).mean()
    return {
        "csv_rows": int(len(events)),
        "csv_share_sender_equals_receiver": float(same.mean()),
        "csv_same_account_but_different_bank": float(
            (same & (events["src_bank"] != events["dst_bank"])).mean()
        ),
        "csv_share_sender_equals_receiver_by_payment_format": {
            str(k): float(v) for k, v in by_format.items()
        },
        "csv_distinct_sender_accounts": len(src_set),
        "csv_distinct_receiver_accounts": len(dst_set),
        "csv_sender_and_receiver_account_sets_identical": src_set == dst_set,
        "pattern_share_sender_equals_receiver": float(
            (patterns["src_account"].astype(str) == patterns["dst_account"].astype(str)).mean()
        ),
    }


def format_account_columns(report: dict) -> str:
    lines = ["", "Sender versus receiver account columns in the CSV"]
    for key, val in report.items():
        lines.append(f"  {key}: {val}")
    return "\n".join(lines) + "\n"


def _plain(value):
    if isinstance(value, (np.floating, float)):
        return float(value)
    return str(value)


def format_diagnosis(report: dict) -> str:
    """Human-readable text for the report from diagnose_matching."""
    n = report["n_pattern_lines"]
    lines = [
        "RingSentinel pattern-to-CSV matching diagnosis (read-only)",
        f"CSV rows: {report['n_csv_rows']:,}   pattern lines: {n:,}   "
        f"exact-duplicate pattern lines: {report['pattern_lines_exact_duplicates']:,}",
        f"CSV rows sharing ts, an account or the paid amount with a pattern line: "
        f"{report['candidate_csv_rows']:,}",
        "",
        "Ranges",
    ]
    for name, (lo, hi) in report["ranges"].items():
        lines.append(f"  {name}: {lo}  ..  {hi}")

    def block(title: str, mapping: dict) -> None:
        lines.extend(["", title])
        for key, val in mapping.items():
            lines.append(f"  {key:<42} {val:>8,}  ({val / max(n, 1):.1%})")

    block(
        "Progressive match levels (pattern lines with a CSV row agreeing on these fields)",
        report["progressive_match_lines"],
    )
    block(
        "Leave-one-field-out (all ten fields except one; a jump points at that field)",
        report["leave_one_field_out_match_lines"],
    )
    block("Account-pair levels", report["account_pair_levels"])
    matched = report["matched_with_occurrence_logic"]
    lines.append(f"\nMatched with the production occurrence logic: {matched:,}")

    lines.extend(["", "Pattern value present anywhere in the CSV column (fraction of lines)"])
    for key, val in report["pattern_value_present_in_csv_column"].items():
        lines.append(f"  {key:<42} {val:.1%}")

    lines.extend(["", "Vocabulary"])
    for key, info in report["vocabulary"].items():
        lines.append(
            f"  {key}: csv {info['csv_distinct']} distinct, patterns {info['pattern_distinct']} "
            f"distinct; only in patterns: {info['only_in_patterns']}"
        )

    for title, key in (
        ("Nearest CSV row between the same two accounts", "nearest_by_account_pair"),
        ("Nearest CSV row from the same source account", "nearest_by_src_account"),
    ):
        info = report[key]
        lines.extend(
            [
                "",
                f"{title}: {info['lines_with_candidate']:,} lines "
                f"({info['fraction_of_pattern_lines']:.1%})",
            ]
        )
        for sub in (
            "field_agreement_with_nearest_row",
            "time_offset_minutes_top10",
            "time_offset_minutes_quantiles",
            "amount_paid_ratio_csv_over_pattern",
        ):
            if sub in info:
                lines.append(f"  {sub}: {info[sub]}")

    lines.extend(["", "First unmatched pattern lines"])
    for ex in report["unmatched_examples"]:
        lines.append(f"  line {ex['line_no']}: pattern {ex['pattern']}")
        lines.append(f"      nearest csv row: {ex['nearest_csv_row']}")
        if "fields_that_differ" in ex:
            lines.append(f"      fields that differ: {ex['fields_that_differ']}")
    return "\n".join(lines) + "\n"
