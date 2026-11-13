"""Ingestor: types, labelling from the patterns file, validation and the full D2 run."""

import json

import numpy as np
import pandas as pd
import pytest
from ringsentinel.config import Settings
from ringsentinel.ingest.normalize import (
    ValidationError,
    add_amount_inr,
    attach_labels,
    check_label_rate,
    load_fx_rates,
    normalize,
    read_transactions,
    validate_events,
)
from ringsentinel.ingest.patterns import parse_patterns

FX = load_fx_rates(Settings().fx_rates_path)


def test_read_transactions_keeps_ids_as_strings_and_sorts_by_time(synthetic):
    events = read_transactions(synthetic["trans_path"], chunksize=500)  # several chunks
    assert len(events) == synthetic["n_rows"]
    assert events["ts"].is_monotonic_increasing
    assert events["event_id"].nunique() == len(events)
    accounts = set(events["src_account"].cat.categories)
    assert "812E34560" in accounts  # not turned into a float
    assert "010" in set(events["src_bank"].cat.categories)  # leading zero kept
    # sender and receiver share one category set, so their codes are comparable
    assert list(events["src_account"].cat.categories) == list(events["dst_account"].cat.categories)
    recv_cats = list(events["recv_currency"].cat.categories)
    assert recv_cats == list(events["pay_currency"].cat.categories)
    assert str(events["src_account"].dtype) == "category"


def test_chunk_size_does_not_change_the_result(synthetic):
    a = read_transactions(synthetic["trans_path"], chunksize=300)
    b = read_transactions(synthetic["trans_path"], chunksize=100_000)
    pd.testing.assert_frame_equal(a, b)


def test_event_id_is_original_file_position(synthetic):
    events = read_transactions(synthetic["trans_path"])
    lines = synthetic["trans_path"].read_text().splitlines()[1:]
    row = events.iloc[100]
    fields = lines[int(row["event_id"])].split(",")
    assert fields[2] == str(row["src_account"]) and fields[4] == str(row["dst_account"])


def test_amount_inr_uses_payment_currency_and_rejects_unknown_currency(synthetic):
    events = add_amount_inr(read_transactions(synthetic["trans_path"]), FX)
    sample = events[events["pay_currency"] == "Rupee"].iloc[0]
    assert sample["amount_inr"] == pytest.approx(sample["amount_paid"] * 1.0)
    with pytest.raises(ValidationError, match="No INR rate"):
        add_amount_inr(read_transactions(synthetic["trans_path"]), {"Euro": 1.0})


def test_labels_match_every_pattern_line_exactly_once(synthetic):
    events = add_amount_inr(read_transactions(synthetic["trans_path"]), FX)
    patterns = parse_patterns(synthetic["patterns_path"])
    labelled, summary = attach_labels(events, patterns)
    assert summary["pattern_lines"] == synthetic["n_pattern_lines"]
    assert summary["pattern_lines_unmatched"] == 0
    # one CSV row is an exact duplicate of a laundering row: only one of the two is labelled
    assert int(labelled["is_illicit"].sum()) == synthetic["n_pattern_lines"]
    assert labelled["ring_id"].notna().sum() == synthetic["n_pattern_lines"]
    assert summary["label_source"] == "patterns_file_only"
    assert set(labelled["ring_id"].dropna().unique()) == set(range(1, synthetic["n_blocks"] + 1))


def test_unmatched_pattern_lines_are_counted(synthetic):
    events = add_amount_inr(read_transactions(synthetic["trans_path"]), FX)
    patterns = parse_patterns(synthetic["patterns_path"])
    patterns.loc[0, "amount_paid"] += 1.0  # no CSV row has this amount
    _, summary = attach_labels(events, patterns)
    assert summary["pattern_lines_unmatched"] == 1
    assert summary["illicit_events"] == synthetic["n_pattern_lines"] - 1


def test_label_rate_bounds():
    check_label_rate(0.0006)
    with pytest.raises(ValidationError):
        check_label_rate(0.0)
    with pytest.raises(ValidationError):
        check_label_rate(0.5)


def test_validate_events_flags_problems(synthetic):
    events = add_amount_inr(read_transactions(synthetic["trans_path"]), FX)
    assert validate_events(events)["ok"] is True
    broken = events.copy()
    broken.loc[3, "ts"] = pd.NaT
    with pytest.raises(ValidationError, match="ts"):
        validate_events(broken)
    broken = events.copy()
    broken.loc[5, "amount_paid"] = np.inf
    with pytest.raises(ValidationError, match="non-finite"):
        validate_events(broken)


def test_normalize_end_to_end_writes_files_and_report(synthetic):
    settings = Settings(data_dir=synthetic["data_dir"])
    report = normalize(settings, chunksize=700)
    assert settings.events_path.exists() and settings.rings_truth_path.exists()
    assert report["labels"]["illicit_events"] == synthetic["n_pattern_lines"]
    assert report["rings"]["n_rings"] == synthetic["n_blocks"]
    assert report["profile"]["self_loops"] >= 20
    saved = json.loads(settings.ingest_report_path.read_text())
    assert saved["variant"] == "HI-Small"

    events = pd.read_parquet(settings.events_path)
    assert str(events["src_account"].dtype) == "category"
    assert str(events["ring_id"].dtype) == "Int32"
    rings = pd.read_parquet(settings.rings_truth_path)
    assert rings["n_pattern_lines"].sum() == synthetic["n_pattern_lines"]
    assert (rings["n_matched_events"] == rings["n_pattern_lines"]).all()
    assert (rings["first_ts"] <= rings["last_ts"]).all()


def test_normalize_fails_when_patterns_do_not_belong_to_the_csv(synthetic):
    settings = Settings(data_dir=synthetic["data_dir"])
    text = synthetic["patterns_path"].read_text().replace(",ACH,1", ",Wire,1")
    synthetic["patterns_path"].write_text(text)
    with pytest.raises(ValidationError, match="could not be matched"):
        normalize(settings)


def test_csv_with_label_column_is_supported(tmp_path, synthetic):
    """If another download includes 'Is Laundering', that column is used as the label."""
    lines = synthetic["trans_path"].read_text().splitlines()
    patterns = parse_patterns(synthetic["patterns_path"])
    keys = {
        (r.ts.strftime("%Y/%m/%d %H:%M"), r.src_account, r.dst_account)
        for r in patterns.itertuples()
    }
    out = [lines[0] + ",Is Laundering"]
    for line in lines[1:]:
        f = line.split(",")
        out.append(line + (",1" if (f[0], f[2], f[4]) in keys else ",0"))
    labelled = tmp_path / "labelled.csv"
    labelled.write_text("\n".join(out) + "\n")
    events = add_amount_inr(read_transactions(labelled), FX)
    labelled_events, summary = attach_labels(events, patterns)
    assert summary["label_source"] == "csv_label_column"
    assert summary["illicit_events"] >= synthetic["n_pattern_lines"]  # includes the duplicate row
    assert "label_raw" not in labelled_events.columns


def test_large_amounts_match_whatever_the_trailing_zeros(tmp_path):
    """Equal decimal amounts must match even when written differently (e.g. 1.04e12 values)."""
    big = "1046302363293.48"
    csv_text = (
        "Timestamp,From Bank,Account,To Bank,Account,Amount Received,Receiving Currency,"
        "Amount Paid,Payment Currency,Payment Format\n"
        f"2022/09/01 00:01,010,A1,020,B1,{big},Yen,{big},Yen,ACH\n"
        "2022/09/01 00:02,010,A1,020,B1,0.000001,Bitcoin,0.000001,Bitcoin,Bitcoin\n"
    )
    pat_text = (
        "BEGIN LAUNDERING ATTEMPT - CYCLE\n"
        f"2022/09/01 00:01,010,A1,020,B1,{big}0,Yen,{big}0,Yen,ACH,1\n"
        "2022/09/01 00:02,010,A1,020,B1,0.000001,Bitcoin,0.000001,Bitcoin,Bitcoin,1\n"
        "END LAUNDERING ATTEMPT - CYCLE\n"
    )
    (tmp_path / "t.csv").write_text(csv_text)
    (tmp_path / "p.txt").write_text(pat_text)
    events = add_amount_inr(read_transactions(tmp_path / "t.csv"), FX)
    _, summary = attach_labels(events, parse_patterns(tmp_path / "p.txt"))
    assert summary["pattern_lines_unmatched"] == 0 and summary["illicit_events"] == 2
