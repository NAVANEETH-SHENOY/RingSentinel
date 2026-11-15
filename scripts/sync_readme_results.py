r"""Copy the generated result tables into README.md, or check that README already matches them.

    python scripts\sync_readme_results.py            # rewrite the block between the markers
    python scripts\sync_readme_results.py --check    # exit 1 if README differs (CI and tests)

The tables come from `docs/EVALUATION_RESULTS.md` (written by `scripts/reproduce.py`) and
`docs/RESULTS_TABLE.md` (written by `scripts/run_stage08.py table`), copied verbatim, so the
README can never show a number that the reproduction script did not print.
`scripts/reproduce.py` calls this at the end of a run.

README must contain the two marker lines:
    <!-- RESULTS:BEGIN -->
    <!-- RESULTS:END -->
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BEGIN, END = "<!-- RESULTS:BEGIN -->", "<!-- RESULTS:END -->"

# (heading in docs/EVALUATION_RESULTS.md, title shown in README)
SECTIONS = (
    ("## All detectors on the temporal test split", "All detectors on the temporal test split"),
    ("## Detection latency (retrospective lower bound)", "Detection latency"),
    ("## Ablation", "Ablation"),
    (
        "## Robustness: random removal of transfers from the test-window graph",
        "Robustness: random removal of transfers from the test-window graph",
    ),
)


class SyncError(Exception):
    pass


def section_body(text: str, heading: str) -> str:
    """Lines under `heading` up to the next level-2 heading, stripped."""
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == heading) + 1
    except StopIteration as exc:
        raise SyncError(f"heading not found in docs/EVALUATION_RESULTS.md: {heading}") from exc
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start:end]).strip()


def build_block(root: Path) -> str:
    results = root / "docs" / "EVALUATION_RESULTS.md"
    two = root / "docs" / "RESULTS_TABLE.md"
    for path in (results, two):
        if not path.is_file():
            raise SyncError(f"missing {path.relative_to(root).as_posix()}; run the pipeline first")
    results_text = results.read_text(encoding="utf-8")
    parts = [
        "_Generated: do not edit by hand. Source: `docs/EVALUATION_RESULTS.md` (from "
        "`scripts/reproduce.py`) and `docs/RESULTS_TABLE.md` (from `scripts/run_stage08.py "
        "table`). Regenerate with `python scripts\\sync_readme_results.py`._",
        "",
    ]
    parts += [ln for ln in results_text.splitlines()[:12] if ln.startswith(("Variant:", "Rupee"))]
    for heading, title in SECTIONS:
        parts += ["", f"**{title}**", "", section_body(results_text, heading)]
    two_text = two.read_text(encoding="utf-8")
    lines = two_text.splitlines()
    table_lines = [ln for ln in lines if ln.startswith("|")]
    notes = [ln for ln in lines if ln.startswith("Ring-")]
    # A blank line must separate the note from the table, or Markdown reads it as a table row.
    parts += ["", "**Two datasets, by detector role**", "", *table_lines, "", *notes]
    return "\n".join(p for i, p in enumerate(parts) if not (p == "" and i and parts[i - 1] == ""))


def render(readme: str, block: str) -> str:
    if (
        readme.count(BEGIN) != 1
        or readme.count(END) != 1
        or readme.index(BEGIN) > readme.index(END)
    ):
        raise SyncError(f"README.md needs exactly one {BEGIN} line followed by one {END} line")
    head, rest = readme.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    return f"{head}{BEGIN}\n\n{block}\n\n{END}{tail}"


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="do not write; exit 1 if out of date")
    args = parser.parse_args(argv)
    readme_path = root / "README.md"
    try:
        current = readme_path.read_text(encoding="utf-8")
        wanted = render(current, build_block(root))
    except SyncError as exc:
        print(f"sync_readme_results: {exc}")
        return 1
    if wanted == current:
        print("sync_readme_results: README results block is up to date")
        return 0
    if args.check:
        print("sync_readme_results: README results block is OUT OF DATE; run "
              "python scripts\\sync_readme_results.py")  # fmt: skip
        return 1
    readme_path.write_text(wanted, encoding="utf-8")
    print("sync_readme_results: README results block rewritten")
    return 0


if __name__ == "__main__":
    sys.exit(main())
