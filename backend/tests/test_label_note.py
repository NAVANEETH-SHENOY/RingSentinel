"""The baseline metrics note must describe the label source the ingest actually used."""

import json

from ringsentinel.config import Settings
from ringsentinel.stage01 import _label_note


def _settings(tmp_path) -> Settings:
    settings = Settings(data_dir=tmp_path)  # temp folder: never touches the real data
    settings.ingest_report_path.parent.mkdir(parents=True, exist_ok=True)
    return settings


def test_note_names_the_csv_label_column(tmp_path):
    settings = _settings(tmp_path)
    report = {"labels": {"label_source": "csv_label_column"}}
    settings.ingest_report_path.write_text(json.dumps(report), encoding="utf-8")
    note = _label_note(settings)
    assert "Is Laundering" in note
    assert "patterns file only" not in note


def test_note_names_the_patterns_fallback(tmp_path):
    settings = _settings(tmp_path)
    report = {"labels": {"label_source": "patterns_file_only"}}
    settings.ingest_report_path.write_text(json.dumps(report), encoding="utf-8")
    assert "patterns file only" in _label_note(settings)


def test_note_admits_when_the_report_is_missing(tmp_path):
    settings = _settings(tmp_path)
    assert "unknown" in _label_note(settings)
