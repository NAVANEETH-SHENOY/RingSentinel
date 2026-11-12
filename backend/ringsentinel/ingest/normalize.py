"""Normalize raw transactions to the event table (data stage D2) and attach ring labels.

Facts from the owner's schema report that shaped this module:
  * The corrected HI-Small download has an 11th column, 'Is Laundering', and it is the label
    source (is_illicit). Pattern lines supply only ring_id and ring_type, and cover a subset of
    the illicit rows. An older 10-column download without that column is still supported: then
    is_illicit falls back to "matched a pattern line" (see DATA.md).
  * Account ids such as '8123E4560' parse as numbers (even infinity) if type inference runs,
    so every id is read and kept as an opaque string.
  * Bank ids have leading zeros and are kept as text.
  * The file is not in time order; event_id is the 0-based row position in the raw file.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.api.types import union_categoricals

from ringsentinel.config import Settings
from ringsentinel.ingest.patterns import parse_patterns
from ringsentinel.ingest.schema import (
    INTERNAL_NAMES,
    KEY_COLUMNS,
    STRING_KEY_COLUMNS,
    TIMESTAMP_FORMAT,
    check_header,
)

LABEL_RATE_MIN = 0.0002  # 0.02 percent
LABEL_RATE_MAX = 0.01  # 1 percent
MAX_UNMATCHED_FRACTION = 0.01
# Share of rows whose sender and receiver account are the same string. In the owner's file the
# self-transfer format "Reinvestment" alone is about 9.5 percent of rows, so a share above one
# half means the sender column is a copy of the receiver column, not real senders.
MAX_SELF_TRANSFER_FRACTION = 0.5


class ValidationError(ValueError):
    """A data-stage validation check failed."""


def load_fx_rates(path: Path) -> dict[str, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {k: float(v) for k, v in payload["inr_per_unit"].items()}


def parse_amounts(values: pd.Series) -> np.ndarray:
    """Parse amount text with Python's correctly rounded float().

    pandas' fast parser can differ in the last bit on large amounts (the data reaches ~1e12),
    which would stop pattern lines from matching their CSV rows. The patterns parser also uses
    float(), so equal decimal values give equal doubles whatever their trailing zeros.
    """
    return np.array(values.tolist(), dtype="float64")


def read_transactions(path: Path, chunksize: int = 1_000_000) -> pd.DataFrame:
    """Read the raw CSV in chunks into a typed event table sorted by time.

    Bank, account and currency columns become categoricals that share one category set between
    the sender and receiver sides, so codes are comparable across the two sides.
    """
    with path.open("r", encoding="utf-8", newline="") as handle:
        has_label = check_header(next(csv.reader(handle)))
    names = [*INTERNAL_NAMES, *(["label_raw"] if has_label else [])]

    ts_parts: list[np.ndarray] = []
    recv_parts: list[np.ndarray] = []
    paid_parts: list[np.ndarray] = []
    label_parts: list[np.ndarray] = []
    cat_parts: dict[str, list[pd.Categorical]] = {c: [] for c in STRING_KEY_COLUMNS}

    reader = pd.read_csv(
        path,
        header=None,
        skiprows=1,
        names=names,
        dtype=str,
        keep_default_na=False,
        chunksize=chunksize,
    )
    for chunk in reader:
        ts_parts.append(pd.to_datetime(chunk["ts"], format=TIMESTAMP_FORMAT).to_numpy())
        recv_parts.append(parse_amounts(chunk["amount_received"]))
        paid_parts.append(parse_amounts(chunk["amount_paid"]))
        if has_label:
            label_parts.append(pd.to_numeric(chunk["label_raw"]).to_numpy("int8"))
        for col in STRING_KEY_COLUMNS:
            cat_parts[col].append(pd.Categorical(chunk[col]))

    n = sum(len(part) for part in ts_parts)
    if n == 0:
        raise ValidationError(f"{path} has a header but no rows")

    def shared(left: str, right: str) -> tuple[pd.Categorical, pd.Categorical]:
        merged = union_categoricals(cat_parts[left] + cat_parts[right], sort_categories=True)
        return merged[:n], merged[n:]

    src_bank, dst_bank = shared("src_bank", "dst_bank")
    src_account, dst_account = shared("src_account", "dst_account")
    recv_currency, pay_currency = shared("recv_currency", "pay_currency")
    payment_format = union_categoricals(cat_parts["payment_format"], sort_categories=True)

    events = pd.DataFrame(
        {
            "event_id": np.arange(n, dtype="int64"),
            "ts": np.concatenate(ts_parts),
            "src_bank": src_bank,
            "src_account": src_account,
            "dst_bank": dst_bank,
            "dst_account": dst_account,
            "amount_received": np.concatenate(recv_parts),
            "recv_currency": recv_currency,
            "amount_paid": np.concatenate(paid_parts),
            "pay_currency": pay_currency,
            "payment_format": payment_format,
        }
    )
    if has_label:
        events["label_raw"] = np.concatenate(label_parts)
    return events.sort_values("ts", kind="stable").reset_index(drop=True)


def check_sender_accounts(events: pd.DataFrame) -> float:
    """Fail early if the sender account column is (nearly) a copy of the receiver column.

    Such a file has no real sender-to-receiver edges, so neither the entity graph nor pattern
    matching can work. Returns the self-transfer share when the check passes.
    """
    share = float((events["src_account"] == events["dst_account"]).mean())
    if share > MAX_SELF_TRANSFER_FRACTION:
        raise ValidationError(
            f"{share:.1%} of rows have the same sender and receiver account "
            f"(limit {MAX_SELF_TRANSFER_FRACTION:.0%}). The sender account column looks like a "
            "copy of the receiver column, so this transactions file has lost its senders. "
            "Obtain an intact copy of the transactions file; do not work around this."
        )
    return share


def add_amount_inr(events: pd.DataFrame, rates: dict[str, float]) -> pd.DataFrame:
    """Add amount_inr = amount_paid converted at the fixed per-currency rate (placeholder rates)."""
    categories = list(events["pay_currency"].cat.categories)
    missing = [c for c in categories if c not in rates]
    if missing:
        raise ValidationError(
            f"No INR rate for currencies: {missing}. Edit config/fx_rates_inr.json"
        )
    table = np.array([rates[c] for c in categories], dtype="float64")
    codes = events["pay_currency"].cat.codes.to_numpy()
    events["amount_inr"] = events["amount_paid"].to_numpy() * table[codes]
    return events


def attach_labels(events: pd.DataFrame, patterns: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Match pattern lines to CSV rows and add ring_id, ring_type and is_illicit.

    Matching uses all ten transaction fields. When several CSV rows are identical, the n-th
    pattern line with that content is matched to the n-th such row (in file order).
    """
    n_events = len(events)
    summary: dict = {"pattern_lines": int(len(patterns))}
    ring_by_event: dict[int, int] = {}
    type_by_event: dict[int, str] = {}
    unmatched = 0

    if len(patterns):
        mask = events["ts"].isin(patterns["ts"].unique()) & events["src_account"].isin(
            patterns["src_account"].unique()
        )
        cand = events.loc[mask, ["event_id", *KEY_COLUMNS]].copy()
        for col in STRING_KEY_COLUMNS:
            cand[col] = cand[col].astype(str)
        cand = cand.sort_values("event_id")
        cand["occ"] = cand.groupby(list(KEY_COLUMNS), sort=False).cumcount()

        pats = patterns[["line_no", "ring_id", "ring_type", *KEY_COLUMNS]].copy()
        pats["occ"] = pats.groupby(list(KEY_COLUMNS), sort=False).cumcount()
        merged = pats.merge(
            cand[["event_id", "occ", *KEY_COLUMNS]], on=[*KEY_COLUMNS, "occ"], how="left"
        )
        matched = merged.dropna(subset=["event_id"])
        unmatched = len(merged) - len(matched)
        ids = matched["event_id"].astype("int64").to_numpy()
        if len(set(ids.tolist())) != len(ids):
            raise ValidationError("A CSV row was matched to more than one pattern line")
        ring_by_event = dict(zip(ids.tolist(), matched["ring_id"].tolist(), strict=True))
        type_by_event = dict(zip(ids.tolist(), matched["ring_type"].tolist(), strict=True))

    ring_series = events["event_id"].map(ring_by_event)
    events["ring_id"] = ring_series.astype("Int32")
    events["ring_type"] = pd.Categorical(events["event_id"].map(type_by_event))

    if "label_raw" in events.columns:
        events["is_illicit"] = (events["label_raw"] == 1).astype("int8")
        summary["label_source"] = "csv_label_column"
        summary["pattern_rows_with_csv_label_zero"] = int(
            ((events["label_raw"] == 0) & events["ring_id"].notna()).sum()
        )
        events = events.drop(columns=["label_raw"])
    else:
        events["is_illicit"] = events["ring_id"].notna().astype("int8")
        summary["label_source"] = "patterns_file_only"

    summary["pattern_lines_unmatched"] = int(unmatched)
    summary["pattern_lines_matched"] = int(len(patterns) - unmatched)
    summary["illicit_events"] = int(events["is_illicit"].sum())
    summary["label_rate"] = float(events["is_illicit"].sum() / n_events)
    return events, summary


def build_rings_truth(events: pd.DataFrame, patterns: pd.DataFrame) -> pd.DataFrame:
    """One row per ring with size and time span, from matched events."""
    ringed = events.loc[events["ring_id"].notna()]
    if ringed.empty:
        return pd.DataFrame(
            columns=[
                "ring_id", "ring_type", "ring_detail", "n_pattern_lines", "n_matched_events",
                "n_accounts", "first_ts", "last_ts",
            ]
        )  # fmt: skip
    ids = ringed["ring_id"].astype("int64")
    accounts = pd.DataFrame(
        {
            "ring_id": np.concatenate([ids.to_numpy(), ids.to_numpy()]),
            "account": np.concatenate(
                [
                    ringed["src_account"].astype(str).to_numpy(),
                    ringed["dst_account"].astype(str).to_numpy(),
                ]
            ),
        }
    )
    per_ring = pd.DataFrame(
        {
            "n_matched_events": ids.groupby(ids).size(),
            "first_ts": ringed["ts"].groupby(ids).min(),
            "last_ts": ringed["ts"].groupby(ids).max(),
        }
    )
    per_ring["n_accounts"] = accounts.groupby("ring_id")["account"].nunique()
    meta = patterns.groupby("ring_id").agg(
        ring_type=("ring_type", "first"),
        ring_detail=("ring_detail", "first"),
        n_pattern_lines=("line_no", "size"),
    )
    out = meta.join(per_ring, how="left").reset_index()
    out["n_matched_events"] = out["n_matched_events"].fillna(0).astype("int64")
    return out[
        [
            "ring_id", "ring_type", "ring_detail", "n_pattern_lines", "n_matched_events",
            "n_accounts", "first_ts", "last_ts",
        ]
    ]  # fmt: skip


def check_label_rate(rate: float) -> None:
    if not (LABEL_RATE_MIN <= rate <= LABEL_RATE_MAX):
        raise ValidationError(
            f"Illicit rate {rate:.6f} is outside the expected range "
            f"[{LABEL_RATE_MIN}, {LABEL_RATE_MAX}]. Labels may not have attached correctly."
        )


def validate_events(events: pd.DataFrame) -> dict:
    """Run the D2 checks: no nulls in key fields, sorted, finite positive amounts, unique ids."""
    problems: list[str] = []
    for col in ("ts", "src_account", "dst_account"):
        nulls = int(events[col].isna().sum())
        if nulls:
            problems.append(f"{col} has {nulls} null values")
    if not events["ts"].is_monotonic_increasing:
        problems.append("events are not sorted by ts")
    if events["event_id"].duplicated().any():
        problems.append("event_id is not unique")
    for col in ("amount_received", "amount_paid", "amount_inr"):
        values = events[col].to_numpy()
        if not np.isfinite(values).all():
            problems.append(f"{col} has non-finite values")
        if (values < 0).any():
            problems.append(f"{col} has negative values")
    if problems:
        raise ValidationError("; ".join(problems))
    return {"ok": True, "rows": int(len(events))}


def profile_events(events: pd.DataFrame) -> dict:
    """Facts about the data that later stages and the docs rely on."""
    pairs = pd.concat(
        [
            pd.DataFrame(
                {
                    "account": events["src_account"].astype(str),
                    "bank": events["src_bank"].astype(str),
                }
            ),
            pd.DataFrame(
                {
                    "account": events["dst_account"].astype(str),
                    "bank": events["dst_bank"].astype(str),
                }
            ),
        ]
    ).drop_duplicates()
    banks_per_account = pairs.groupby("account").size()
    per_day = events["ts"].dt.strftime("%Y-%m-%d").value_counts().sort_index()
    return {
        "n_events": int(len(events)),
        "n_accounts": int(len(events["src_account"].cat.categories)),
        "ts_min": str(events["ts"].min()),
        "ts_max": str(events["ts"].max()),
        "events_per_day": {k: int(v) for k, v in per_day.items()},
        "self_loops": int((events["src_account"] == events["dst_account"]).sum()),
        "cross_currency_rows": int((events["recv_currency"] != events["pay_currency"]).sum()),
        "accounts_seen_with_more_than_one_bank": int((banks_per_account > 1).sum()),
        "payment_format_counts": {
            k: int(v) for k, v in events["payment_format"].value_counts().items()
        },
    }


def normalize(settings: Settings, chunksize: int = 1_000_000) -> dict:
    """Run D2 end to end for the configured variant and write the processed files."""
    events = read_transactions(settings.trans_path, chunksize=chunksize)
    check_sender_accounts(events)
    events = add_amount_inr(events, load_fx_rates(settings.fx_rates_path))

    patterns = parse_patterns(settings.patterns_path)
    events, label_summary = attach_labels(events, patterns)

    unmatched_fraction = label_summary["pattern_lines_unmatched"] / max(len(patterns), 1)
    if unmatched_fraction > MAX_UNMATCHED_FRACTION:
        raise ValidationError(
            f"{label_summary['pattern_lines_unmatched']} of {len(patterns)} pattern lines "
            "could not be matched to CSV rows; the two files may not belong together."
        )
    check_label_rate(label_summary["label_rate"])
    checks = validate_events(events)

    rings = build_rings_truth(events, patterns)
    report = {
        "variant": settings.dataset_variant,
        "checks": checks,
        "labels": label_summary,
        "rings": {
            "n_rings": int(len(rings)),
            "by_type": {k: int(v) for k, v in rings["ring_type"].value_counts().items()},
        },
        "profile": profile_events(events),
    }

    settings.processed_dir.mkdir(parents=True, exist_ok=True)
    events.to_parquet(settings.events_path, index=False)
    rings.to_parquet(settings.rings_truth_path, index=False)
    settings.ingest_report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
