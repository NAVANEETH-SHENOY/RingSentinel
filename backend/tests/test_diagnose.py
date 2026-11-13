"""The matching diagnostic must point at the field that was deliberately perturbed."""

import pandas as pd
import pytest
from ringsentinel.ingest.diagnose import diagnose_matching, format_diagnosis
from ringsentinel.ingest.normalize import read_transactions
from ringsentinel.ingest.patterns import parse_patterns


def _diagnose(synthetic, mutate):
    events = read_transactions(synthetic["trans_path"], chunksize=700)
    patterns = parse_patterns(synthetic["patterns_path"])
    return diagnose_matching(events, mutate(patterns))


def test_identical_files_match_everything(synthetic):
    report = _diagnose(synthetic, lambda p: p)
    n = synthetic["n_pattern_lines"]
    assert report["n_pattern_lines"] == n
    assert report["progressive_match_lines"]["all_10_fields"] == n
    assert report["matched_with_occurrence_logic"] == n
    assert report["unmatched_examples"] == []
    assert "matching diagnosis" in format_diagnosis(report)


def test_timestamp_shift_is_localised_to_ts(synthetic):
    def shift(p):
        p = p.copy()
        p["ts"] = p["ts"] + pd.Timedelta(minutes=37)
        return p

    report = _diagnose(synthetic, shift)
    assert report["progressive_match_lines"]["all_10_fields"] == 0
    loo = report["leave_one_field_out_match_lines"]
    assert loo["without_ts"] == synthetic["n_pattern_lines"]
    assert max(v for k, v in loo.items() if k != "without_ts") == 0
    offsets = report["nearest_by_account_pair"]["time_offset_minutes_top10"]
    assert "-37" in offsets


def test_changed_bank_is_localised_to_that_bank(synthetic):
    def change(p):
        p = p.copy()
        p["src_bank"] = p["src_bank"] + "9"
        return p

    report = _diagnose(synthetic, change)
    loo = report["leave_one_field_out_match_lines"]
    assert loo["without_src_bank"] == synthetic["n_pattern_lines"]
    assert loo["without_dst_bank"] == 0
    assert report["pattern_value_present_in_csv_column"]["src_bank"] == 0.0
    assert report["vocabulary"]["src_bank"]["only_in_patterns"]


def test_scaled_amounts_report_the_ratio(synthetic):
    def scale(p):
        p = p.copy()
        p["amount_paid"] = p["amount_paid"] * 2
        p["amount_received"] = p["amount_received"] * 2
        return p

    report = _diagnose(synthetic, scale)
    assert report["progressive_match_lines"]["all_10_fields"] == 0
    ratio = report["nearest_by_account_pair"]["amount_paid_ratio_csv_over_pattern"]
    assert ratio["0.5"] == pytest.approx(0.5)


def test_disjoint_accounts_are_visible_in_value_presence(synthetic):
    def rename(p):
        p = p.copy()
        p["src_account"] = "Z" + p["src_account"]
        p["dst_account"] = "Z" + p["dst_account"]
        return p

    report = _diagnose(synthetic, rename)
    present = report["pattern_value_present_in_csv_column"]
    assert present["src_account"] == 0.0 and present["dst_account"] == 0.0
    assert report["nearest_by_account_pair"]["lines_with_candidate"] == 0


def test_diagnostic_does_not_modify_its_inputs(synthetic):
    events = read_transactions(synthetic["trans_path"], chunksize=700)
    patterns = parse_patterns(synthetic["patterns_path"])
    before_e, before_p = events.copy(), patterns.copy()
    diagnose_matching(events, patterns)
    pd.testing.assert_frame_equal(events, before_e)
    pd.testing.assert_frame_equal(patterns, before_p)


# --- endpoint (leg) analysis -------------------------------------------------------------
HEADER = (
    "Timestamp,From Bank,Account,To Bank,Account,Amount Received,Receiving Currency,"
    "Amount Paid,Payment Currency,Payment Format\n"
)
ROW_A = "2022/09/01 00:06,021174,800737690,021174,800737690,2848.96,Euro,3338.36,US Dollar,ACH"
ROW_B = "2022/09/01 00:06,021174,80011F990,012,80011F990,2848.96,Euro,2848.96,Euro,ACH"
PAT = "2022/09/01 00:06,021174,800737690,012,80011F990,2848.96,Euro,2848.96,Euro,ACH,1"
NOISE = "2022/09/01 00:07,010,8000AAAAA,011,8000BBBBB,10.0,Euro,10.0,Euro,Wire"


def _legs(tmp_path, csv_rows, pattern_lines):
    from ringsentinel.ingest.diagnose import diagnose_legs

    trans = tmp_path / "t.csv"
    trans.write_text(HEADER + "\n".join(csv_rows) + "\n", encoding="utf-8")
    pats = tmp_path / "p.txt"
    body = "\n".join(pattern_lines)
    head = "BEGIN LAUNDERING ATTEMPT - FAN-OUT:  Max 1 hops"
    pats.write_text(f"{head}\n{body}\nEND LAUNDERING ATTEMPT - FAN-OUT\n", encoding="utf-8")
    return diagnose_legs(read_transactions(trans), parse_patterns(pats))


def test_legs_detects_the_stitched_case_seen_in_the_real_files(tmp_path):
    report = _legs(tmp_path, [ROW_A, ROW_B, NOISE], [PAT])
    assert report["classes"]["stitched_src_from_one_row_dst_from_another"] == 1
    detail = report["stitched_detail"]
    assert detail["row_A_is_self_transfer"] == 1.0
    assert detail["row_B_is_self_transfer"] == 1.0  # same account, banks 021174 -> 012
    assert detail["pattern_paid_fields_equal_row_B"] == 1.0
    assert detail["pattern_paid_fields_equal_row_A"] == 0.0
    assert detail["row_A_pay_currency_differs_from_recv_currency"] == 1.0


def test_legs_exact_row_is_classified_exact(tmp_path):
    exact = "2022/09/01 00:06,021174,800737690,012,80011F990,2848.96,Euro,2848.96,Euro,ACH"
    report = _legs(tmp_path, [exact, ROW_A, NOISE], [PAT])
    assert report["classes"]["exact_row_exists"] == 1


def test_legs_no_anchor_and_swapped(tmp_path):
    swapped = "2022/09/01 00:06,012,80011F990,021174,800737690,2848.96,Euro,2848.96,Euro,ACH"
    report = _legs(tmp_path, [swapped, NOISE], [PAT])
    assert report["classes"]["endpoints_swapped_in_csv"] == 1
    report = _legs(tmp_path, [NOISE], [PAT])
    assert report["classes"]["no_anchor_row"] == 1
    assert sum(report["classes"].values()) == report["n_pattern_lines"]


# --- sender account column integrity -----------------------------------------------------
def _copy_receiver_into_sender(trans_path):
    lines = trans_path.read_text(encoding="utf-8").splitlines()
    out = [lines[0]]
    for line in lines[1:]:
        f = line.split(",")
        f[2] = f[4]  # the 'From' Account column becomes a copy of the 'To' Account column
        out.append(",".join(f))
    trans_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def test_account_column_report_on_intact_and_overwritten_files(synthetic):
    from ringsentinel.ingest.diagnose import diagnose_account_columns

    patterns = parse_patterns(synthetic["patterns_path"])
    intact = diagnose_account_columns(read_transactions(synthetic["trans_path"]), patterns)
    assert intact["csv_share_sender_equals_receiver"] < 0.05

    _copy_receiver_into_sender(synthetic["trans_path"])
    broken = diagnose_account_columns(read_transactions(synthetic["trans_path"]), patterns)
    assert broken["csv_share_sender_equals_receiver"] == 1.0
    assert broken["csv_sender_and_receiver_account_sets_identical"] is True
    assert broken["pattern_share_sender_equals_receiver"] == 0.0


def test_ingest_stops_with_an_accurate_message_when_senders_are_lost(synthetic):
    from ringsentinel.config import Settings
    from ringsentinel.ingest.normalize import ValidationError, normalize

    _copy_receiver_into_sender(synthetic["trans_path"])
    settings = Settings(data_dir=synthetic["data_dir"])
    with pytest.raises(ValidationError, match="copy of the receiver column"):
        normalize(settings)
