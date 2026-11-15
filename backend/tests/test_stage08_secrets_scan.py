"""Stage 08: the secrets scanner finds key-shaped strings, never prints them, skips fixtures."""

import subprocess

import pytest
import secrets_scan as scan

# Built at run time so this file itself contains no key-shaped literal.
GROQ = "gsk_" + "Ab3" * 10
GOOGLE = "AIza" + "Sy" * 17 + "Q"
GITHUB = "ghp_" + "a1B2" * 9
AWS = "AKIA" + "ABCDEFGHIJKLMNOP"
PRIVATE = "-----BEGIN " + "RSA PRIVATE KEY-----"
REAL_LOOKING = "q8Zk3VnR7pLw2XyT9mBd"
KAGGLE = "0123456789abcdef" * 2


@pytest.mark.parametrize(
    ("line", "rule"),
    [
        (f'key = "{GROQ}"', "groq-key"),
        (f"GEMINI={GOOGLE}", "google-api-key"),
        (f"token: {GITHUB}", "github-token"),
        (f"aws {AWS}", "aws-access-key"),
        (PRIVATE, "private-key"),
        (f'{{"username":"x","key":"{KAGGLE}"}}', "kaggle-key"),
        (f"RS_ANALYST_TOKEN={REAL_LOOKING}", "assigned-secret"),
        (f'api_key = "{REAL_LOOKING}"', "assigned-secret"),
    ],
)
def test_each_rule_fires(line, rule):
    assert rule in {f.rule for f in scan.scan_text(line, "f.py")}


@pytest.mark.parametrize(
    "line",
    [
        "GROQ_API_KEY=<your key here>",
        "RS_ANALYST_TOKEN=change-me-to-a-long-random-value",
        "# GEMINI_API_KEY=",
        'TOKEN = "integration-token-0123"',
        "secret = value.removeprefix('Bearer ')",
        "api_key = os.environ.get('X')",
        f"fixture = '{GROQ}'  # secrets-ok",
        "password = None",
        "RS_ANALYST_TOKEN=${RS_ANALYST_TOKEN}",
    ],
)
def test_placeholders_code_and_marked_fixtures_are_ignored(line):
    assert scan.scan_text(line, "f.py") == []


def test_findings_never_contain_the_secret():
    findings = scan.scan_text(f"RS_ANALYST_TOKEN={REAL_LOOKING}\nkey={GROQ}", "a.env")
    assert len(findings) >= 2
    for finding in findings:
        text = str(finding)
        assert REAL_LOOKING not in text and GROQ not in text
        assert len(finding.preview) <= 4
    assert str(findings[0]).startswith("a.env:1")


def test_line_numbers_are_reported():
    findings = scan.scan_text(f"\n\n\nkey={GROQ}", "x.txt")
    assert [f.where for f in findings] == ["x.txt:4"]


@pytest.fixture
def repo(tmp_path, monkeypatch):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.org")
    git("config", "user.name", "t")
    (tmp_path / ".gitignore").write_text(
        ".env\nkaggle.json\ndata/audit/\ndata/raw/*\ndata/processed/*\n", encoding="utf-8"
    )
    monkeypatch.setattr(scan, "ROOT", tmp_path)
    return tmp_path, git


def test_clean_repo_passes(repo):
    root, git = repo
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "init")
    assert scan.main([]) == 0


def test_secret_in_a_working_file_is_found(repo, capsys):
    root, _ = repo
    (root / "settings.py").write_text(f'KEY = "{GROQ}"\n', encoding="utf-8")
    assert scan.main(["--no-history"]) == 1
    out = capsys.readouterr().out
    assert "settings.py:1" in out and GROQ not in out


def test_ignored_env_file_is_not_scanned_but_tracked_one_is_a_problem(repo, capsys):
    root, git = repo
    (root / ".env").write_text(f"GROQ_API_KEY={GROQ}\n", encoding="utf-8")
    assert scan.main(["--no-history"]) == 0  # ignored: this is where real keys belong
    git("add", "-f", ".env")
    git("commit", "-qm", "oops")
    assert scan.main(["--no-history"]) == 1
    out = capsys.readouterr().out
    assert ".env is tracked" in out and GROQ not in out


def test_missing_ignore_rule_is_reported(repo, capsys):
    root, _ = repo
    (root / ".gitignore").write_text(".env\n", encoding="utf-8")
    assert scan.main(["--no-history"]) == 1
    assert "kaggle.json is NOT git-ignored" in capsys.readouterr().out


def test_a_key_that_was_committed_and_removed_is_found_in_history(repo, capsys):
    root, git = repo
    (root / "old.py").write_text(f'KEY = "{GROQ}"\n', encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "add key")
    (root / "old.py").write_text("KEY = None\n", encoding="utf-8")
    git("commit", "-qam", "remove key")
    assert scan.main(["--no-history"]) == 0  # gone from the working tree
    assert scan.main([]) == 1  # but still in history
    out = capsys.readouterr().out
    assert "history:" in out and "old.py" in out and GROQ not in out


def test_history_scan_needs_a_git_checkout(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(scan, "ROOT", tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    assert scan.main([]) == 2
    assert scan.main(["--no-history"]) == 0
    capsys.readouterr()
