"""Read, validate and hash a snapshot bundle. Shared by the exporter and the API."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from jsonschema import Draft202012Validator

from ringsentinel.snapshots.schemas import SCHEMAS

BUNDLE_FILES = tuple(sorted(SCHEMAS))
DATA_FILES = tuple(name for name in BUNDLE_FILES if name != "meta.json")


class SnapshotError(Exception):
    """The bundle is missing, malformed, inconsistent or does not match its hashes."""


def clean(obj: Any) -> Any:
    """Make a value JSON-safe and deterministic: numpy to Python, NaN and inf to None."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [clean(v) for v in obj.tolist()]
    if isinstance(obj, np.generic):
        return clean(obj.item())
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if isinstance(obj, Path):
        return str(obj)
    return obj


def canonical_text(obj: Any) -> str:
    """The one serialization used for every bundle file (sorted keys, 2 spaces, final newline)."""
    text = json.dumps(clean(obj), sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
    return text + "\n"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def bundle_id_from(file_hashes: dict[str, str]) -> str:
    lines = "\n".join(f"{name}:{file_hashes[name]}" for name in sorted(file_hashes))
    return sha256_bytes(lines.encode("utf-8"))


def validate_document(name: str, document: Any) -> None:
    """Raise SnapshotError listing every schema violation of one bundle file."""
    validator = Draft202012Validator(SCHEMAS[name])
    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))
    if errors:
        shown = "; ".join(f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
                          for e in errors[:5])  # fmt: skip
        raise SnapshotError(f"{name} violates its schema ({len(errors)} problem(s)): {shown}")


@dataclass(frozen=True)
class Bundle:
    directory: Path
    meta: dict
    queue: dict
    cases: dict
    metrics: dict
    drift: dict
    replay: dict

    @property
    def bundle_id(self) -> str:
        return self.meta["bundle_id"]


def load_bundle(directory: Path) -> Bundle:
    """Load a bundle from disk and check schemas, file hashes and cross references."""
    directory = Path(directory)
    if not directory.is_dir():
        raise SnapshotError(
            f"snapshot folder not found: {directory}. Run scripts/export_snapshots.py first."
        )
    raw: dict[str, bytes] = {}
    docs: dict[str, Any] = {}
    for name in BUNDLE_FILES:
        path = directory / name
        if not path.is_file():
            raise SnapshotError(f"snapshot file missing: {path}")
        raw[name] = path.read_bytes()
        try:
            docs[name] = json.loads(raw[name].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SnapshotError(f"{name} is not valid JSON: {exc}") from exc
        validate_document(name, docs[name])
    meta = docs["meta.json"]
    actual = {name: sha256_bytes(raw[name]) for name in DATA_FILES}
    if actual != meta["files"]:
        bad = sorted(n for n in DATA_FILES if actual[n] != meta["files"].get(n))
        raise SnapshotError(f"file hash mismatch against meta.json for: {', '.join(bad)}")
    if bundle_id_from(actual) != meta["bundle_id"]:
        raise SnapshotError("bundle_id in meta.json does not match the file hashes")
    case_ids = set(docs["cases.json"]["cases"])
    queue_ids = [item["ring_id"] for item in docs["queue.json"]["items"]]
    if len(set(queue_ids)) != len(queue_ids):
        raise SnapshotError("queue.json lists a ring_id twice")
    if set(queue_ids) != case_ids:
        raise SnapshotError("queue.json and cases.json do not list the same rings")
    if meta["n_rings_exported"] != len(queue_ids):
        raise SnapshotError("meta.n_rings_exported does not match the queue length")
    ranks = [item["rank"] for item in docs["queue.json"]["items"]]
    if ranks != list(range(1, len(ranks) + 1)):
        raise SnapshotError("queue ranks must run 1..n in order")
    return Bundle(
        directory, meta, docs["queue.json"], docs["cases.json"], docs["metrics.json"],
        docs["drift.json"], docs["replay.json"],
    )  # fmt: skip
