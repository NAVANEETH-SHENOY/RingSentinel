"""Guards scripts/inspect_schema.py on tiny synthetic files (not the real dataset)."""

import inspect_schema

CSV_TEXT = (
    "ts,bankA,acct,bankB,acct,amt,fmt,flag\n"
    "2022/09/01 00:01,1,A1,2,B1,10.5,Wire,0\n"
    "2022/09/01 00:02,1,A1,3,C1,20,ACH,1\n"
    "2022/09/01 00:03,2,B1,3,,5,Wire,0\n"
)

PATTERN_TEXT = (
    "BEGIN SOMETHING - ONE\n"
    "2022/09/01 00:01,1,A1,2,B1,10.5,Wire,1\n"
    "END SOMETHING - ONE\n"
    "\n"
    "BEGIN SOMETHING - TWO\n"
    "2022/09/01 00:02,1,A1,3,C1,20,ACH,1\n"
    "END SOMETHING - TWO\n"
)


def test_inspect_csv_reports_duplicates_counts_and_values(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text(CSV_TEXT, encoding="utf-8")
    report = inspect_schema.inspect_csv(path)

    assert report["row_count"] == 3
    assert report["ragged_rows"] == 0
    assert report["duplicate_header_names"] == ["acct"]
    assert report["first_column_sorted_ascending_as_text"] is True
    assert len(report["sha256"]) == 64

    by_pos = {c["position"]: c for c in report["columns"]}
    assert by_pos[2]["name"] == by_pos[4]["name"] == "acct"  # repeated names kept apart
    assert by_pos[2]["empty"] == 0 and by_pos[4]["empty"] == 1  # empties not merged by name
    assert by_pos[5]["num_min"] == 5 and by_pos[5]["num_max"] == 20
    assert by_pos[7]["distinct_values"] == {"0": 2, "1": 1}
    assert by_pos[6]["distinct_values"] == {"Wire": 2, "ACH": 1}


def test_inspect_csv_counts_empty_cells_and_detects_unsorted_first_column(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text("a,b\n2,x\n1,\n", encoding="utf-8")
    report = inspect_schema.inspect_csv(path)
    assert report["first_column_sorted_ascending_as_text"] is False
    assert {c["name"]: c["empty"] for c in report["columns"]} == {"a": 0, "b": 1}


def test_inspect_csv_flags_ragged_rows(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text("a,b\n1,2\n3\n", encoding="utf-8")
    assert inspect_schema.inspect_csv(path)["ragged_rows"] == 1


def test_distinct_values_are_capped(tmp_path):
    path = tmp_path / "t.csv"
    body = "\n".join(f"v{i}" for i in range(inspect_schema.MAX_DISTINCT + 5))
    path.write_text("a\n" + body + "\n", encoding="utf-8")
    col = inspect_schema.inspect_csv(path)["columns"][0]
    assert col["distinct_capped"] is True and col["distinct_values"] is None


def test_inspect_patterns_makes_no_layout_assumptions(tmp_path):
    path = tmp_path / "p.txt"
    path.write_text(PATTERN_TEXT, encoding="utf-8")
    report = inspect_schema.inspect_patterns(path)
    assert report["total_lines"] == 7
    assert report["lines_starting_with_digit"] == 2
    assert report["other_line_count"] == 4
    prefixes = dict(report["other_prefix_top"])
    assert prefixes["BEGIN SOMETHING"] == 2 and prefixes["END SOMETHING"] == 2
    assert report["head"][0] == "BEGIN SOMETHING - ONE"


def test_main_writes_report_and_returns_codes(tmp_path):
    trans = tmp_path / "t.csv"
    pats = tmp_path / "p.txt"
    out = tmp_path / "out" / "report.txt"
    trans.write_text(CSV_TEXT, encoding="utf-8")
    pats.write_text(PATTERN_TEXT, encoding="utf-8")

    code = inspect_schema.main(
        ["--trans", str(trans), "--patterns", str(pats), "--out", str(out)]
    )
    assert code == 0
    text = out.read_text(encoding="utf-8")
    assert "=== SCHEMA REPORT ===" in text and "duplicate_header_names=['acct']" in text

    assert inspect_schema.main(["--trans", str(tmp_path / "missing.csv")]) == 2
