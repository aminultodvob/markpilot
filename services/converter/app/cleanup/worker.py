"""Background cleanup.

Three sweeps run on a timer for as long as the service is up:

* expired sessions, so abandoned uploads do not linger past their TTL;
* orphaned workspace directories, which is how the service recovers from a
  crash that left files behind with no session tracking them;
* stale rate-limit buckets, which are pure memory.

The loop runs in a daemon thread rather than an async task so a long blocking
``rmtree`` on a large workspace cannot stall the event loop that is serving
conversions.
"""

from __future__ import annotations

import threading

from app.config import Settings
from app.logging_setup import get_logger
from app.security.ratelimit import RateLimiter
from app.sessions.manager import SessionManager

logger = get_logger(__name__)


class CleanupWorker:
    def __init__(
        self,
        sessions: SessionManager,
        settings: Settings,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._rate_limiter = rate_limiter
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        # An immediate orphan sweep reclaims anything a previous run left.
        self._sweep_orphans()
        self._thread = threading.Thread(
            target=self._run, name="cleanup-worker", daemon=True
        )
        self._thread.start()
        logger.info(
            "cleanup worker started",
            extra={"interval_seconds": self._settings.cleanup_interval_seconds},
        )

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5)
        self._thread = None

    def run_once(self) -> dict[str, int]:
        """Run every sweep once. Exposed for tests and for startup."""
        expired = self._sessions.sweep_expired()
        orphans = self._sweep_orphans()
        buckets = self._rate_limiter.sweep() if self._rate_limiter else 0
        return {
            "expired_sessions": expired,
            "orphaned_workspaces": orphans,
            "rate_limit_buckets": buckets,
        }

    def _sweep_orphans(self) -> int:
        try:
            return self._sessions.sweep_orphans()
        except Exception:  # pragma: no cover - cleanup must never crash
            logger.warning("orphan sweep failed", exc_info=True)
            return 0

    def _run(self) -> None:
        interval = max(self._settings.cleanup_interval_seconds, 5)
        while not self._stop.wait(interval):
            try:
                counts = self.run_once()
                if any(counts.values()):
                    logger.info("cleanup sweep", extra=counts)
            except Exception:  # pragma: no cover - keep the loop alive
                logger.warning("cleanup sweep failed", exc_info=True)
