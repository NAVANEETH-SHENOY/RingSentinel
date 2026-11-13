"""Checks against the REAL HI-Small files. Skipped automatically when they are not present
(for example in CI); run on the owner's machine where data/raw holds the downloads."""

import csv

import pytest
from ringsentinel.config import Settings
from ringsentinel.ingest import manifest
from ringsentinel.ingest.patterns import parse_patterns
from ringsentinel.ingest.schema import RAW_COLUMNS, check_header

SETTINGS = Settings()
HAVE_TRANS = SETTINGS.trans_path.exists()
HAVE_PATTERNS = SETTINGS.patterns_path.exists()


@pytest.mark.skipif(not HAVE_TRANS, reason="real HI-Small_Trans.csv not present")
def test_real_csv_header_matches_the_expected_schema():
    with SETTINGS.trans_path.open(encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle))

    assert tuple(header) in (RAW_COLUMNS, (*RAW_COLUMNS, "Is Laundering"))
    assert check_header(header) is ("Is Laundering" in header)


@pytest.mark.skipif(not (HAVE_TRANS and HAVE_PATTERNS), reason="real raw files not present")
def test_real_files_match_the_committed_manifest():
    loaded = manifest.load_manifest(SETTINGS.manifest_path)
    assert manifest.verify_files(loaded, "HI-Small", SETTINGS.raw_dir) == []


@pytest.mark.skipif(not HAVE_PATTERNS, reason="real HI-Small_Patterns.txt not present")
def test_real_patterns_file_has_the_counts_seen_in_the_schema_report():
    frame = parse_patterns(SETTINGS.patterns_path)
    assert frame["ring_id"].nunique() == 370
    assert len(frame) == 3209
    assert set(frame["pattern_label"]) == {1}
