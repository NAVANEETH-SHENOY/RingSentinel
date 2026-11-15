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
        self._last_sweep = clock()

    def check(self, client: str, bucket: str) -> float | None:
        """Record a hit. Returns None if allowed, else seconds until a slot frees up."""
        limit = self._limits.get(bucket, 0)
        if limit <= 0:
            return None
        now = self._clock()
        with self._lock:
            hits = self._window(client, bucket, now)
            if len(hits) >= limit:
                return max(0.0, WINDOW_SECONDS - (now - hits[0]))
            hits.append(now)
            return None

    def blocked(self, client: str, bucket: str) -> float | None:
        """Seconds until the client may try again if its bucket is full; records nothing."""
        limit = self._limits.get(bucket, 0)
        if limit <= 0:
            return None
        now = self._clock()
        with self._lock:
            hits = self._hits.get((client, bucket))
            if hits is None:
                return None
            while hits and now - hits[0] >= WINDOW_SECONDS:
                hits.popleft()
            if len(hits) >= limit:
                return max(0.0, WINDOW_SECONDS - (now - hits[0]))
            return None

    def record(self, client: str, bucket: str) -> None:
        """Count one event (for example a failed login) without deciding anything."""
        if self._limits.get(bucket, 0) <= 0:
            return
        now = self._clock()
        with self._lock:
            self._window(client, bucket, now).append(now)

    def _window(self, client: str, bucket: str, now: float) -> deque[float]:
        if len(self._hits) > MAX_TRACKED_KEYS or now - self._last_sweep >= WINDOW_SECONDS:
            self._last_sweep = now
            self._prune(now)
        hits = self._hits.setdefault((client, bucket), deque())
        while hits and now - hits[0] >= WINDOW_SECONDS:
            hits.popleft()
        return hits

    def _prune(self, now: float) -> None:
        for key in [k for k, v in self._hits.items() if not v or now - v[-1] >= WINDOW_SECONDS]:
            del self._hits[key]
        if len(self._hits) > MAX_TRACKED_KEYS:  # still too many live keys: drop the stalest
            stalest = sorted(self._hits, key=lambda k: self._hits[k][-1] if self._hits[k] else 0)
            for key in stalest[: len(self._hits) - MAX_TRACKED_KEYS * 9 // 10]:
                del self._hits[key]
