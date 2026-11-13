"""Checksum manifest for raw files (data stage D1).

data/raw/MANIFEST.json is committed to git; the raw files themselves are not.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

SCHEMA_VERSION = 1


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def build_entry(path: Path) -> dict:
    return {"size_bytes": path.stat().st_size, "sha256": sha256_file(path)}


def load_manifest(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "datasets": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def add_variant(manifest: dict, variant: str, files: list[Path]) -> dict:
    """Record the given raw files for one dataset variant (overwrites that variant's entry)."""
    manifest.setdefault("schema_version", SCHEMA_VERSION)
    manifest.setdefault("datasets", {})
    manifest["datasets"][variant] = {"files": {p.name: build_entry(p) for p in files}}
    return manifest


def verify_files(manifest: dict, variant: str, raw_dir: Path) -> list[str]:
    """Compare raw files with the manifest. Returns a list of problems (empty = OK)."""
    entry = manifest.get("datasets", {}).get(variant)
    if not entry:
        return [f"No manifest entry for variant {variant!r}. Run with --write-manifest first."]
    problems: list[str] = []
    for name, expected in sorted(entry["files"].items()):
        path = raw_dir / name
        if not path.exists():
            problems.append(f"{name}: file missing in {raw_dir}")
            continue
        if path.stat().st_size != expected["size_bytes"]:
            problems.append(
                f"{name}: size {path.stat().st_size} != manifest {expected['size_bytes']}"
            )
            continue
        actual = sha256_file(path)
        if actual != expected["sha256"]:
            problems.append(f"{name}: sha256 {actual} != manifest {expected['sha256']}")
    return problems
