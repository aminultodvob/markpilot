"""In-memory sliding-window rate limiting.

This is an anonymous public converter, so abuse protection cannot rely on
accounts. We limit two things per client: how many jobs are started, and how
many bytes are uploaded, both over a rolling hour.

Deliberately in-process and in-memory: it needs no Redis, and the failure mode
of a restart (counters reset) is acceptable for this threat model. Client keys
are salted hashes of the remote address, so raw IPs are never retained.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field

WINDOW_SECONDS = 3600
# Per-process salt: rotates on restart and never leaves the process, so the
# stored keys are not reversible to an IP address.
_SALT = os.environ.get("RATE_LIMIT_SALT") or secrets.token_hex(16)


def client_key(remote_addr: str | None) -> str:
    """Derive a non-reversible bucket key from a client address."""
    return hashlib.sha256(f"{_SALT}:{remote_addr or 'unknown'}".encode()).hexdigest()[:32]


@dataclass
class _Bucket:
    jobs: deque[float] = field(default_factory=deque)
    uploads: deque[tuple[float, int]] = field(default_factory=deque)

    def prune(self, now: float) -> None:
        cutoff = now - WINDOW_SECONDS
        while self.jobs and self.jobs[0] < cutoff:
            self.jobs.popleft()
        while self.uploads and self.uploads[0][0] < cutoff:
            self.uploads.popleft()

    @property
    def uploaded_bytes(self) -> int:
        return sum(size for _, size in self.uploads)

    @property
    def empty(self) -> bool:
        return not self.jobs and not self.uploads


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    reason: str | None = None
    retry_after_seconds: int = 0


class RateLimiter:
    def __init__(
        self,
        *,
        enabled: bool,
        jobs_per_hour: int,
        upload_mb_per_hour: int,
    ) -> None:
        self._enabled = enabled
        self._jobs_per_hour = jobs_per_hour
        self._upload_bytes_per_hour = upload_mb_per_hour * 1024 * 1024
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def check(self, key: str, upload_bytes: int) -> RateLimitDecision:
        """Test-and-reserve one job plus ``upload_bytes`` for ``key``."""
        if not self._enabled:
            return RateLimitDecision(allowed=True)

        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.setdefault(key, _Bucket())
            bucket.prune(now)

            if len(bucket.jobs) >= self._jobs_per_hour:
                retry = int(WINDOW_SECONDS - (now - bucket.jobs[0])) + 1
                return RateLimitDecision(
                    allowed=False,
                    reason="You've started a lot of conversions in the last hour.",
                    retry_after_seconds=max(retry, 1),
                )

            if bucket.uploaded_bytes + upload_bytes > self._upload_bytes_per_hour:
                oldest = bucket.uploads[0][0] if bucket.uploads else now
                retry = int(WINDOW_SECONDS - (now - oldest)) + 1
                return RateLimitDecision(
                    allowed=False,
                    reason="You've uploaded a lot of data in the last hour.",
                    retry_after_seconds=max(retry, 1),
                )

            bucket.jobs.append(now)
            bucket.uploads.append((now, upload_bytes))
            return RateLimitDecision(allowed=True)

    def sweep(self) -> int:
        """Drop buckets that have fully aged out. Returns how many were removed."""
        now = time.monotonic()
        with self._lock:
            stale = []
            for key, bucket in self._buckets.items():
                bucket.prune(now)
                if bucket.empty:
                    stale.append(key)
            for key in stale:
                del self._buckets[key]
            return len(stale)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()
