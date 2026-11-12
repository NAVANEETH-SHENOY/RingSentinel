"""Header validation (including the repeated 'Account' column) and the checksum manifest."""

import pytest
from ringsentinel.ingest import manifest
from ringsentinel.ingest.schema import RAW_COLUMNS, SchemaError, check_header


def test_real_header_is_accepted_and_has_no_label():
    assert check_header(list(RAW_COLUMNS)) is False
    assert RAW_COLUMNS.count("Account") == 2


def test_optional_label_column_is_detected():
    assert check_header([*RAW_COLUMNS, "Is Laundering"]) is True


def test_unexpected_header_is_rejected_with_a_helpful_message():
    with pytest.raises(SchemaError, match="inspect_schema"):
        check_header(["Timestamp", "From Bank"])
    with pytest.raises(SchemaError):
        check_header([*RAW_COLUMNS, "Something Else"])


def test_manifest_roundtrip_and_verification(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "a.csv").write_text("hello\n")
    (raw / "b.txt").write_text("world\n")
    data = manifest.add_variant({}, "HI-Small", [raw / "a.csv", raw / "b.txt"])
    path = raw / "MANIFEST.json"
    manifest.save_manifest(path, data)
    loaded = manifest.load_manifest(path)
    assert manifest.verify_files(loaded, "HI-Small", raw) == []


def test_manifest_detects_tampering_size_change_and_missing_files(tmp_path):
    raw = tmp_path
    (raw / "a.csv").write_text("hello\n")
    data = manifest.add_variant({}, "HI-Small", [raw / "a.csv"])

    (raw / "a.csv").write_text("hellO\n")  # same size, different content
    assert "sha256" in manifest.verify_files(data, "HI-Small", raw)[0]

    (raw / "a.csv").write_text("hello world\n")  # different size
    assert "size" in manifest.verify_files(data, "HI-Small", raw)[0]

    (raw / "a.csv").unlink()
    assert "missing" in manifest.verify_files(data, "HI-Small", raw)[0]


def test_missing_variant_entry_is_reported(tmp_path):
    problems = manifest.verify_files({"datasets": {}}, "HI-Medium", tmp_path)
    assert len(problems) == 1 and "HI-Medium" in problems[0]
