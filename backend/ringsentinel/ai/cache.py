"""Case-file cache keyed by a hash of everything the case file depends on.

The key covers the ring id (itself a hash of the member accounts), the retained edges, the counts
and amounts, the detector score, the feature list and the prompt version. Change any of them and
the old entry is simply not found. The provider and model are not part of the key: a verified
case file stays valid whichever model wrote it, and its provenance is stored inside it.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from ringsentinel.ai.facts import CaseFacts
from ringsentinel.ai.schemas import PROMPT_VERSION


def input_hash(facts: CaseFacts, prompt_version: str = PROMPT_VERSION) -> str:
    material = {
        "prompt_version": prompt_version,
        "ring_id": facts.ring_id,
        "n_members": facts.n_members,
        "n_transfers": facts.n_transfers,
        "amount_inr": facts.ring_total_inr,
        "score": facts.score,
        "oversized": facts.oversized,
        "coverage": [facts.edges_available, facts.edges_truncated, facts.members_truncated],
        "features": [
            [str(f.get("feature")), f.get("mean_contribution")] for f in facts.top_features
        ],
        "edges": [
            [e.src, e.dst, e.n_transfers, e.total_inr, e.first_ts, e.last_ts]
            for e in facts.edges
        ],
        "nodes": sorted(facts.nodes),
    }  # fmt: skip
    text = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class CaseCache:
    """One JSON file per input hash. Corrupt or unreadable entries count as a miss."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def _path(self, key: str) -> Path:
        if not (len(key) == 64 and all(c in "0123456789abcdef" for c in key)):
            raise ValueError("cache key must be a sha256 hex digest")
        return self.directory / f"{key}.json"

    def get(self, key: str) -> dict | None:
        path = self._path(key)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return None
        if not isinstance(value, dict) or value.get("input_hash") != key:
            return None
        return value

    def put(self, key: str, block: dict) -> None:
        """Write atomically so an interrupted run never leaves half a file."""
        path = self._path(key)
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(block, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)

    def __len__(self) -> int:
        return sum(1 for _ in self.directory.glob("*.json")) if self.directory.is_dir() else 0
