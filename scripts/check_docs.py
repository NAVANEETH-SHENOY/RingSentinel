"""Fail if the docs mention a file path or function that does not exist.

What is checked (in README.md, HANDOVER.md and docs/*.md):
  * Backticked file paths: tokens containing "/" or ending in a known extension.
    Wildcards (*) are matched with glob.
  * Backticked function or class references: `name()` or `path/to/file.py::name()`.

What is skipped:
  * Fenced code blocks.
  * Any line containing [planned] or [generated], optionally with a note such as
    [planned, Stage 01] (files that do not exist in git yet).
  * Tokens with spaces, URLs, placeholders (<>), env-style (%, $), or backslashes.

Run from the repo root:  python scripts/check_docs.py
Exit code 0 = docs consistent, 1 = problems found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DOC_FILES = ("README.md", "HANDOVER.md")
DOC_DIRS = ("docs",)
KNOWN_EXTENSIONS = (
    ".py", ".md", ".txt", ".json", ".toml", ".yml", ".yaml",
    ".parquet", ".csv", ".cfg", ".ini", ".js", ".ts", ".tsx", ".joblib",
)  # fmt: skip
EXCLUDED_DIRS = {".venv", "venv", "node_modules", ".git", "data", "__pycache__"}
SKIP_MARKER = re.compile(r"\[(planned|generated)\b[^\]]*\]")
BACKTICK = re.compile(r"`([^`\n]+)`")
FUNC_REF = re.compile(r"^(?:(?P<path>[\w./-]+\.py)::)?(?P<name>[A-Za-z_]\w*)\(\)$")
PATH_CHARS = re.compile(r"^[\w./*-]+$")
SKIP_CHARS = set("<>$%{}|=\\~ ")


def _strip_fenced_blocks(text: str) -> str:
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return "\n".join(out)


def extract_tokens(text: str) -> list[str]:
    """Return backticked tokens from non-fenced, non-skipped lines."""
    tokens: list[str] = []
    for line in _strip_fenced_blocks(text).splitlines():
        if SKIP_MARKER.search(line):
            continue
        tokens.extend(m.group(1).strip() for m in BACKTICK.finditer(line))
    return tokens


def _python_files(root: Path) -> list[Path]:
    return [
        p
        for p in root.rglob("*.py")
        if not any(part in EXCLUDED_DIRS for part in p.relative_to(root).parts)
    ]


def _defines(py_file: Path, name: str) -> bool:
    pattern = re.compile(rf"^\s*(?:async\s+)?(?:def|class)\s+{re.escape(name)}\b", re.MULTILINE)
    try:
        return bool(pattern.search(py_file.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError):
        return False


def _path_exists(root: Path, token: str) -> bool:
    clean = token.rstrip("/")
    if "*" in clean:
        return any(root.glob(clean))
    return (root / clean).exists()


def check_token(root: Path, token: str, py_files: list[Path]) -> str | None:
    """Return a problem description for one token, or None if it is fine or not checkable."""
    if token.startswith(("http://", "https://")) or any(c in SKIP_CHARS for c in token):
        return None

    func = FUNC_REF.match(token)
    if func:
        name, rel = func.group("name"), func.group("path")
        if rel:
            target = root / rel
            if not target.exists():
                return f"`{token}`: file {rel} does not exist"
            return None if _defines(target, name) else f"`{token}`: {name} not defined in {rel}"
        if any(_defines(p, name) for p in py_files):
            return None
        return f"`{token}`: no function or class named {name} found in any .py file"

    looks_like_path = PATH_CHARS.match(token) and (
        "/" in token or token.lower().endswith(KNOWN_EXTENSIONS)
    )
    if looks_like_path and not _path_exists(root, token):
        return f"`{token}`: path does not exist"
    return None


def doc_files(root: Path) -> list[Path]:
    files = [root / name for name in DOC_FILES if (root / name).exists()]
    for directory in DOC_DIRS:
        folder = root / directory
        if folder.is_dir():
            files.extend(sorted(folder.rglob("*.md")))
    return files


def find_problems(root: Path) -> list[str]:
    """Check every doc file under root. Returns a list of 'file: problem' strings."""
    py_files = _python_files(root)
    problems: list[str] = []
    for doc in doc_files(root):
        text = doc.read_text(encoding="utf-8")
        seen: set[str] = set()
        for token in extract_tokens(text):
            if token in seen:
                continue
            seen.add(token)
            problem = check_token(root, token, py_files)
            if problem:
                problems.append(f"{doc.relative_to(root).as_posix()}: {problem}")
    return problems


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0]).resolve() if args else Path(__file__).resolve().parents[1]
    problems = find_problems(root)
    if problems:
        print(f"check_docs: {len(problems)} problem(s) found")
        for item in problems:
            print(f"  - {item}")
        return 1
    print(f"check_docs: OK ({len(doc_files(root))} doc files checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
