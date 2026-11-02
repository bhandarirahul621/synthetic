"""In-memory, per-key rate limiting (PRD §9.1.6).

A *fixed window* limiter: each key may make ``limit`` requests per 60-second
window. Think of a ticket roll that is refilled every minute. It lives in
process memory, so it resets on restart and is not shared between server
instances; a Redis-backed limiter replaces it when we run more than one.
"""

from __future__ import annotations

import threading
import time


class RateLimiter:
    """Count requests per key in fixed one-minute windows."""

    def __init__(self, limit_per_minute: int, window_s: float = 60.0):
        self.limit = limit_per_minute
        self.window = window_s
        self._lock = threading.Lock()
        self._counts: dict[str, tuple[float, int]] = {}

    def hit(self, key: str) -> tuple[bool, int, int]:
        """Record one request. Returns ``(allowed, remaining, seconds_until_reset)``."""
        now = time.monotonic()
        with self._lock:
            start, count = self._counts.get(key, (now, 0))
            if now - start >= self.window:
                start, count = now, 0
            count += 1
            self._counts[key] = (start, count)
        reset = max(0, int(round(self.window - (now - start))))
        remaining = max(0, self.limit - count)
        return count <= self.limit, remaining, reset
