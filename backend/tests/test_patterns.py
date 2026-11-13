"""Patterns parser, tested on blocks copied from the owner's real HI-Small_Patterns.txt."""

import pytest
from ringsentinel.ingest.patterns import PatternError, parse_patterns

REAL_EXCERPT = """BEGIN LAUNDERING ATTEMPT - CYCLE:  Max 10 hops
2022/09/01 00:03,01467,8013C4030,020,80BC62F10,58702.10,Yuan,58702.10,Yuan,ACH,1
2022/09/01 02:52,020,80BC62F10,0240229,80F025640,7332.87,Swiss Franc,7332.87,Swiss Franc,ACH,1
2022/09/04 15:51,0028628,80ACEE280,01467,8013C4030,7945.55,US Dollar,7945.55,US Dollar,ACH,1
END LAUNDERING ATTEMPT - CYCLE

BEGIN LAUNDERING ATTEMPT - GATHER-SCATTER:  Max 3-degree Fan-In
2022/09/01 00:04,0119,811C597B0,0048309,811C599A0,34254.65,Saudi Riyal,34254.65,Saudi Riyal,ACH,1
2022/09/04 05:03,0048309,811C599A0,0048309,811C599A0,48649.42,Saudi Riyal,48649.42,Saudi Riyal,ACH,1
END LAUNDERING ATTEMPT - GATHER-SCATTER

BEGIN LAUNDERING ATTEMPT - FAN-OUT
2022/09/01 00:06,021174,800737690,012,80011F990,2848.96,Euro,2848.96,Euro,ACH,1
END LAUNDERING ATTEMPT - FAN-OUT
"""


def _write(tmp_path, text):
    path = tmp_path / "p.txt"
    path.write_text(text, encoding="utf-8")
    return path


def test_parses_blocks_types_details_and_fields(tmp_path):
    frame = parse_patterns(_write(tmp_path, REAL_EXCERPT))
    assert len(frame) == 6
    assert frame["ring_id"].tolist() == [1, 1, 1, 2, 2, 3]
    assert frame.groupby("ring_id")["ring_type"].first().tolist() == [
        "CYCLE", "GATHER-SCATTER", "FAN-OUT",
    ]  # fmt: skip
    assert frame.loc[0, "ring_detail"] == "Max 10 hops"
    assert frame.loc[5, "ring_detail"] == ""  # a header with no ':' detail
    first = frame.iloc[0]
    assert first["src_bank"] == "01467" and first["src_account"] == "8013C4030"
    assert first["amount_paid"] == 58702.10 and first["pay_currency"] == "Yuan"
    assert first["pattern_label"] == 1
    assert str(first["ts"]) == "2022-09-01 00:03:00"


def test_keeps_leading_zeros_and_self_loops(tmp_path):
    frame = parse_patterns(_write(tmp_path, REAL_EXCERPT))
    self_loop = frame[(frame["src_account"] == frame["dst_account"])]
    assert len(self_loop) == 1 and self_loop.iloc[0]["src_bank"] == "0048309"


@pytest.mark.parametrize(
    "text, message",
    [
        ("2022/09/01 00:06,1,A,2,B,1.0,Euro,1.0,Euro,ACH,1\n", "outside"),
        ("BEGIN LAUNDERING ATTEMPT - CYCLE\n2022/09/01 00:06,1,A,2,B,1.0,Euro,ACH,1\n", "fields"),
        ("BEGIN LAUNDERING ATTEMPT - CYCLE\nEND LAUNDERING ATTEMPT - FAN-IN\n", "closes"),
        ("END LAUNDERING ATTEMPT - CYCLE\n", "without BEGIN"),
        ("BEGIN LAUNDERING ATTEMPT - CYCLE\n", "open"),
        ("hello\n", "unrecognised"),
    ],
)
def test_malformed_files_raise_clear_errors(tmp_path, text, message):
    with pytest.raises(PatternError, match=message):
        parse_patterns(_write(tmp_path, text))
