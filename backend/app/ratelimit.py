"""A small in-memory sliding-window rate limiter (per client address and bucket).

It lives in one process. With several workers each has its own counters, so the effective limit
is looser. Behind a proxy every request may share the proxy's address; see docs/STAGE_04.md.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

WINDOW_SECONDS = 60.0
MAX_TRACKED_KEYS = 10_000


class RateLimiter:
    def __init__(self, limits: dict[str, int], clock: Callable[[], float] = time.monotonic):
        self._limits = dict(limits)
        self._clock = clock
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, client: str, bucket: str) -> float | None:
        """Record a hit. Returns None if allowed, else seconds until a slot frees up."""
        limit = self._limits.get(bucket, 0)
        if limit <= 0:
            return None
        now = self._clock()
        with self._lock:
            if len(self._hits) > MAX_TRACKED_KEYS:
                self._prune(now)
            hits = self._hits.setdefault((client, bucket), deque())
            while hits and now - hits[0] >= WINDOW_SECONDS:
                hits.popleft()
            if len(hits) >= limit:
                return max(0.0, WINDOW_SECONDS - (now - hits[0]))
            hits.append(now)
            return None

    def _prune(self, now: float) -> None:
        for key in [k for k, v in self._hits.items() if not v or now - v[-1] >= WINDOW_SECONDS]:
            del self._hits[key]
