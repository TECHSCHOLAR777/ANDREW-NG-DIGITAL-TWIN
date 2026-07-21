"""
services/rate_limit.py
─────────────────────────────────────────────────────────────────────────────
In-process token bucket, applied per tenant.

Why this exists: every endpoint was previously unlimited. Generation costs
money, TTS occupies a GPU for seconds at a time, and retrieval runs vector
search over the whole corpus. A single script could exhaust a user's Gemini
quota, saturate the TTS service for everyone, or hold the database pool open.

Scope and honesty about it
──────────────────────────
This limiter is per process and in memory. That is correct for a single
backend instance, which is what this project deploys as today. Behind two or
more replicas each process keeps its own counters, so the effective limit
multiplies by the replica count. When that day comes the fix is Redis with the
same interface, not a different design.

It is deliberately NOT a security boundary. Tenant IDs are client-supplied
until real authentication lands (SEC-02), so a determined caller can rotate
tenant IDs to get fresh buckets. It is a cost and fairness control: it stops
runaway clients, retry storms and accidental infinite loops, which is what
actually goes wrong in practice.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Requests per minute, per tenant, per endpoint class.
# Chat is the expensive one (generation). TTS is GPU-bound. Reads are cheap.
RATE_LIMIT_CHAT  = int(os.getenv("RATE_LIMIT_CHAT", "20"))
RATE_LIMIT_TTS   = int(os.getenv("RATE_LIMIT_TTS", "120"))
RATE_LIMIT_READ  = int(os.getenv("RATE_LIMIT_READ", "240"))
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() != "false"

# Stop the bucket table growing without bound when many tenants appear.
MAX_TRACKED_BUCKETS = int(os.getenv("RATE_LIMIT_MAX_BUCKETS", "10000"))
_IDLE_EVICT_SECONDS = 900


@dataclass
class _Bucket:
    tokens:     float
    capacity:   float
    refill_per_second: float
    last_seen:  float = field(default_factory=time.monotonic)

    def take(self, now: float) -> tuple[bool, float]:
        """
        Attempt to spend one token.

        Returns (allowed, retry_after_seconds). A token bucket is used rather
        than a fixed window because it tolerates natural bursts (a user sending
        three messages quickly) while still holding the average rate, whereas a
        fixed window both allows double-rate bursts across the boundary and
        rejects reasonable ones inside it.
        """
        elapsed = now - self.last_seen
        self.last_seen = now
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_second)

        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True, 0.0

        needed = 1.0 - self.tokens
        return False, needed / self.refill_per_second


class RateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._lock = threading.Lock()

    def check(self, key: str, scope: str, per_minute: int) -> tuple[bool, float]:
        if not RATE_LIMIT_ENABLED or per_minute <= 0:
            return True, 0.0

        now = time.monotonic()
        ident = (scope, key)

        with self._lock:
            bucket = self._buckets.get(ident)
            if bucket is None:
                bucket = _Bucket(
                    tokens=float(per_minute),
                    capacity=float(per_minute),
                    refill_per_second=per_minute / 60.0,
                )
                self._buckets[ident] = bucket
                if len(self._buckets) > MAX_TRACKED_BUCKETS:
                    self._evict_idle(now)

            return bucket.take(now)

    def _evict_idle(self, now: float) -> None:
        """Drop buckets nobody has touched recently. Caller holds the lock."""
        stale = [k for k, b in self._buckets.items() if now - b.last_seen > _IDLE_EVICT_SECONDS]
        for k in stale:
            self._buckets.pop(k, None)

        # If everything is active, drop the least recently used rather than
        # letting the table grow without limit.
        if len(self._buckets) > MAX_TRACKED_BUCKETS:
            ordered = sorted(self._buckets.items(), key=lambda kv: kv[1].last_seen)
            for k, _ in ordered[: len(self._buckets) - MAX_TRACKED_BUCKETS]:
                self._buckets.pop(k, None)
        logger.info("Rate limiter evicted idle buckets; %d remain", len(self._buckets))


limiter = RateLimiter()
