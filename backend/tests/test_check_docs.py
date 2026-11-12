"""Guards scripts/check_docs.py: stale docs must fail, and this repo's own docs must pass."""

from pathlib import Path

import check_docs
from ringsentinel.config import PROJECT_ROOT


def _make_tree(root: Path, doc_text: str) -> None:
    (root / "docs").mkdir()
    (root / "pkg").mkdir()
    source = "def real_func():\n    return 1\n\nclass RealClass:\n    pass\n"
    (root / "pkg" / "mod.py").write_text(source)
    (root / "README.md").write_text(doc_text, encoding="utf-8")


def test_valid_references_pass(tmp_path):
    _make_tree(tmp_path, "See `pkg/mod.py`, `real_func()`, `pkg/mod.py::RealClass()`, `pkg/`.")
    assert check_docs.find_problems(tmp_path) == []


def test_missing_path_fails(tmp_path):
    _make_tree(tmp_path, "See `pkg/missing.py`.")
    problems = check_docs.find_problems(tmp_path)
    assert len(problems) == 1 and "pkg/missing.py" in problems[0]


def test_missing_function_fails(tmp_path):
    _make_tree(tmp_path, "Calls `ghost_function()` somewhere.")
    problems = check_docs.find_problems(tmp_path)
    assert len(problems) == 1 and "ghost_function" in problems[0]


def test_function_in_wrong_file_fails(tmp_path):
    (tmp_path / "other.py").write_text("x = 1\n")
    _make_tree(tmp_path, "See `other.py::real_func()`.")
    problems = check_docs.find_problems(tmp_path)
    assert len(problems) == 1 and "not defined in other.py" in problems[0]


def test_planned_lines_fenced_blocks_and_placeholders_are_skipped(tmp_path):
    text = (
        "Later: `backend/app/main.py` [planned]\n"
        "```\n`fenced/not_checked.py`\n```\n"
        "Env: `%USERPROFILE%\\.kaggle\\kaggle.json`, `docs/STAGE_<NN>.md`.\n"
        "Cmd: `pip install -r x.txt`. Note: `docs/gone.md` [planned, Stage 09]\n"
        "Link: `https://example.com/a/b.py`.\n"
    )
    _make_tree(tmp_path, text)
    assert check_docs.find_problems(tmp_path) == []


def test_glob_patterns(tmp_path):
    _make_tree(tmp_path, "Stage docs: `docs/STAGE_*.md`.")
    assert len(check_docs.find_problems(tmp_path)) == 1
    (tmp_path / "docs" / "STAGE_00.md").write_text("ok\n")
    assert check_docs.find_problems(tmp_path) == []


def test_main_exit_codes(tmp_path):
    _make_tree(tmp_path, "See `pkg/missing.py`.")
    assert check_docs.main([str(tmp_path)]) == 1
    (tmp_path / "README.md").write_text("Nothing to check.\n")
    assert check_docs.main([str(tmp_path)]) == 0


def test_repository_docs_are_consistent():
    """The real docs in this repo must not reference files or functions that do not exist."""
    assert check_docs.find_problems(PROJECT_ROOT) == []
