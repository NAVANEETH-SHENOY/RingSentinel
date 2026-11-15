"""Look for committed secrets (Stage 08 secrets review). Repo root; needs git for history.

    python scripts\\secrets_scan.py               # working files (tracked or not ignored) + history
    python scripts\\secrets_scan.py --no-history  # working files only (fast)

Exit code 0: nothing found. 1: findings (printed WITHOUT the secret: file, line, rule, and the
first four characters). 2: not a git checkout and --no-history was not given.

What it checks
  * key-shaped strings (Groq, Google, GitHub, AWS, Slack, Kaggle, private keys);
  * assignments such as RS_ANALYST_TOKEN=<16+ characters> or API_KEY="<20+ characters>" whose
    value is not an obvious placeholder;
  * that .env, kaggle.json and the audit database are git-ignored and not tracked;
  * that git history never contained a matching line (names the commit, never the value).
A line may carry `secrets-ok` to be skipped (used for deliberate test fixtures).
It is a safety net, not a guarantee. If a real key was ever committed, REVOKE it at the provider;
rewriting history does not un-leak it.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve().relative_to(ROOT).as_posix()

RULES: dict[str, re.Pattern[str]] = {
    "groq-key": re.compile(r"gsk_[A-Za-z0-9]{20,}"),
    "google-api-key": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "github-token": re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    "aws-access-key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "slack-token": re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"),
    "kaggle-key": re.compile(r"[\"']key[\"']\s*:\s*[\"'][0-9a-f]{32}[\"']"),
    "assigned-secret": re.compile(
        r"(?i)\b[A-Z0-9_]*(?:API_KEY|SECRET|TOKEN|PASSWORD|PASSWD)[A-Z0-9_]*\s*[=:]\s*"
        r"[\"']?([A-Za-z0-9_\-./+=]{16,})"
    ),
}
PLACEHOLDER = re.compile(
    r"(?i)(your|change|example|placeholder|dummy|sample|fake|test|xxxx|\.\.\.|<|none|null|"
    r"redacted|secret|token|password|abcdef|0000|1111|aaaa|tttt|\$\{)"
)
CODE_LIKE = re.compile(r"^[A-Za-z_][A-Za-z_.]*$")  # a variable or attribute access, not a value
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".zip", ".parquet",
                 ".joblib", ".sqlite3", ".pdf", ".lock"}  # fmt: skip
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".next", "out",
             ".pytest_cache", ".ruff_cache"}  # fmt: skip
MUST_BE_IGNORED = (".env", "kaggle.json", "data/audit/audit.sqlite3", "data/raw/x.csv",
                   "data/processed/x.parquet")  # fmt: skip
MUST_NOT_BE_TRACKED = {".env", "kaggle.json"}
MUST_NOT_BE_TRACKED_PREFIXES = ("data/audit/",)


@dataclass(frozen=True)
class Finding:
    where: str  # "path:line" or "history:<commit>:<path>"
    rule: str
    preview: str  # first four characters only

    def __str__(self) -> str:
        return f"{self.where}  [{self.rule}]  starts with {self.preview!r}"


def _is_placeholder(value: str) -> bool:
    return bool(PLACEHOLDER.search(value))


def scan_text(text: str, where: str) -> list[Finding]:
    found: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if "secrets-ok" in line:
            continue
        for rule, pattern in RULES.items():
            for match in pattern.finditer(line):
                value = match.group(1) if pattern.groups else match.group(0)
                if rule == "assigned-secret" and (_is_placeholder(value) or CODE_LIKE.match(value)):
                    continue
                if rule != "assigned-secret" and _is_placeholder(value) and len(value) < 12:
                    continue
                found.append(Finding(f"{where}:{number}", rule, value[:4]))
    return found


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)


def is_git_checkout() -> bool:
    return _git("rev-parse", "--is-inside-work-tree").stdout.strip() == "true"


def working_files() -> list[Path]:
    if is_git_checkout():
        out = _git("ls-files", "--cached", "--others", "--exclude-standard", "-z").stdout
        names = [n for n in out.split("\0") if n]
        return [ROOT / n for n in names if (ROOT / n).is_file()]
    return [p for p in ROOT.rglob("*") if p.is_file()
            and not any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts)]  # fmt: skip


def scan_files(paths: Iterable[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        rel = path.relative_to(ROOT).as_posix()
        if rel == SELF or path.suffix.lower() in SKIP_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        findings += scan_text(text, rel)
    return findings


HISTORY_ERE = (
    "gsk_[A-Za-z0-9]{20,}", "AIza[0-9A-Za-z_-]{35}", "gh[pousr]_[A-Za-z0-9]{30,}",
    "AKIA[0-9A-Z]{16}", "xox[baprs]-[A-Za-z0-9-]{10,}",
    "-----BEGIN (RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----",
    "\"key\" *: *\"[0-9a-f]{32}\"",
)  # fmt: skip  (POSIX extended syntax, because git -G does not understand Python's)


def scan_history() -> list[Finding]:
    """Commits whose diffs ever ADDED or REMOVED a line matching a key-shaped rule.

    The value is never printed. A failure of git itself is reported as a finding so that a
    broken scan cannot look like a clean one.
    """
    log = _git("log", "--all", "-E", "-G", "|".join(HISTORY_ERE), "--format=COMMIT %h",
               "--name-only")  # fmt: skip
    if log.returncode != 0:
        return [Finding("history:git-failed", "history-scan-error", log.stderr.strip()[:4])]
    findings: list[Finding] = []
    commit = ""
    for line in log.stdout.splitlines():
        if line.startswith("COMMIT "):
            commit = line.split()[1]
        elif line.strip() and line.strip() != SELF:
            where = f"history:{commit}:{line.strip()}"
            findings.append(Finding(where, "key-shaped-in-history", "?"))
    return findings


def check_ignore_rules() -> list[str]:
    problems: list[str] = []
    if not is_git_checkout():
        return problems
    for name in MUST_BE_IGNORED:
        if _git("check-ignore", "-q", name).returncode != 0:
            problems.append(f"{name} is NOT git-ignored (add it to .gitignore)")
    tracked = _git("ls-files").stdout.splitlines()
    for path in tracked:
        if path in MUST_NOT_BE_TRACKED or path.startswith(MUST_NOT_BE_TRACKED_PREFIXES):
            problems.append(f"{path} is tracked by git; run: git rm --cached {path}")
    return problems


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    history = "--no-history" not in args
    if history and not is_git_checkout():
        print("Not a git checkout: history cannot be scanned. Re-run with --no-history.")
        return 2
    findings = scan_files(working_files())
    problems = check_ignore_rules()
    if history:
        findings += scan_history()
    for finding in findings:
        print(f"FOUND   {finding}")
    for problem in problems:
        print(f"PROBLEM {problem}")
    if findings or problems:
        print("\nIf any hit is a real key: revoke it at the provider first, then remove it.")
        return 1
    print("secrets_scan: nothing found" + ("" if history else " (history not scanned)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
