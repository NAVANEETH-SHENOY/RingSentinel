"""Read-only view of the snapshot bundle held in memory by the API."""

from __future__ import annotations

from pathlib import Path

from ringsentinel.snapshots.bundle import Bundle, load_bundle


class SnapshotStore:
    def __init__(self, directory: Path):
        self.bundle: Bundle = load_bundle(directory)
        self._queue = {item["ring_id"]: item for item in self.bundle.queue["items"]}

    @property
    def bundle_id(self) -> str:
        return self.bundle.bundle_id

    def has_ring(self, ring_id: str) -> bool:
        return ring_id in self._queue

    def queue_items(self) -> list[dict]:
        return self.bundle.queue["items"]

    def case(self, ring_id: str) -> dict | None:
        return self.bundle.cases["cases"].get(ring_id)
