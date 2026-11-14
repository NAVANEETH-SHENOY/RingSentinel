"""Merge the AI layer's output (D10 `ai_cases.json`) into the snapshot bundle (D12).

Only the `ai` block of a case is ever replaced. Scores, ranks, values, members and edges are
copied through unchanged, and `queue.json` is not touched, so nothing an AI block says can move a
ring in the queue. A block is applied only if its `input_hash` still matches the case it was
written for; a block for an older version of the case is counted as stale and ignored.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path

from ringsentinel.ai.cache import input_hash
from ringsentinel.ai.facts import CaseFacts
from ringsentinel.snapshots.bundle import (
    DATA_FILES,
    Bundle,
    bundle_id_from,
    canonical_text,
    clean,
    load_bundle,
    sha256_bytes,
    validate_document,
)

AI_SOURCE_NAME = "ai_cases.json"


def ai_document_hash(ai_doc: dict) -> str:
    return sha256_bytes(canonical_text(ai_doc).encode("utf-8"))


def apply_ai_blocks(cases: dict[str, dict], ai_doc: dict) -> dict[str, int]:
    """Put matching AI blocks into `cases` (in place). Returns applied/stale/missing counts."""
    blocks = ai_doc.get("cases", {})
    counts = {"applied": 0, "stale": 0, "missing": 0}
    for ring_id, case in cases.items():
        block = blocks.get(ring_id)
        if block is None:
            counts["missing"] += 1
        elif block.get("input_hash") != input_hash(CaseFacts(case)):
            counts["stale"] += 1
        else:
            case["ai"] = clean(block)
            counts["applied"] += 1
    return counts


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(tmp, path)


def merge_ai_into_bundle(directory: Path, ai_doc: dict) -> tuple[Bundle, dict[str, int]]:
    """Rewrite `cases.json` and `meta.json` of an existing bundle with the AI blocks applied."""
    directory = Path(directory)
    bundle = load_bundle(directory)  # refuses a bundle that is already inconsistent
    cases_doc = copy.deepcopy(bundle.cases)
    counts = apply_ai_blocks(cases_doc["cases"], ai_doc)
    validate_document("cases.json", cases_doc)  # before anything is written
    cases_text = canonical_text(cases_doc)
    texts = {"cases.json": cases_text}
    hashes = {
        name: sha256_bytes(texts[name].encode("utf-8")) if name in texts
        else sha256_bytes((directory / name).read_bytes())
        for name in DATA_FILES
    }  # fmt: skip
    meta = copy.deepcopy(bundle.meta)
    meta["files"] = hashes
    meta["bundle_id"] = bundle_id_from(hashes)
    meta["sources"] = {**meta["sources"], AI_SOURCE_NAME: ai_document_hash(ai_doc)}
    _atomic_write(directory / "cases.json", cases_text)
    _atomic_write(directory / "meta.json", canonical_text(meta))
    return load_bundle(directory), counts
