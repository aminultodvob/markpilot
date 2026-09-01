"""Sessions, jobs and the temporary workspace.

Everything here is deliberately ephemeral. There is no database and no user
account: a session is a random id, a bearer token, a directory under the
system temp root, and an expiry.

Three rules this module enforces:

* **Identifiers are unguessable.** Session and token values come from
  ``secrets``, never from a filename, an IP address or a timestamp.
* **User input never becomes a path.** Uploads are stored under generated ids;
  the original name is metadata carried alongside, used only for display and
  for naming the download.
* **Nothing outlives its TTL.** Sessions expire, and the cleanup worker removes
  their directories whether or not the client ever came back.

Converted Markdown is held in memory on the session rather than written to
disk, so results disappear with the process and are never persisted.
"""

from __future__ import annotations

import secrets
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Final, Literal

from app.config import Settings
from app.conversion.errors import NotAuthorizedError, SessionNotFoundError
from app.conversion.result import ConversionResult
from app.logging_setup import get_logger

logger = get_logger(__name__)

SESSION_ID_BYTES = 16
TOKEN_BYTES = 32
FILE_ID_BYTES = 12

#: The states a file can be in. Declared as a Literal so the API response
#: model and the session store cannot drift apart.
FileStatus = Literal["queued", "processing", "completed", "failed", "cancelled"]

STATUS_QUEUED: Final[FileStatus] = "queued"
STATUS_PROCESSING: Final[FileStatus] = "processing"
STATUS_COMPLETED: Final[FileStatus] = "completed"
STATUS_FAILED: Final[FileStatus] = "failed"
STATUS_CANCELLED: Final[FileStatus] = "cancelled"

TERMINAL_STATUSES: Final[tuple[FileStatus, ...]] = (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_CANCELLED,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class JobFile:
    """One uploaded file and, eventually, its conversion result."""

    id: str
    filename: str
    size: int
    status: FileStatus = STATUS_QUEUED
    stage: str | None = None
    markdown: str | None = None
    result: ConversionResult | None = None
    error_code: str | None = None
    error_message: str | None = None
    error_detail: str | None = None
    #: Set for files that came out of an uploaded archive.
    source_archive: str | None = None
    #: Storage path, never exposed through the API.
    stored_path: Path | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


@dataclass
class Job:
    id: str
    session_id: str
    files: list[JobFile] = field(default_factory=list)
    created_at: datetime = field(default_factory=_now)
    cancelled: bool = False

    @property
    def status(self) -> FileStatus:
        """Aggregate status derived from the files, so it cannot drift."""
        if self.cancelled and not all(f.is_terminal for f in self.files):
            return STATUS_CANCELLED
        if any(f.status == STATUS_PROCESSING for f in self.files):
            return STATUS_PROCESSING
        if any(f.status == STATUS_QUEUED for f in self.files):
            return STATUS_QUEUED
        if self.files and all(f.status == STATUS_FAILED for f in self.files):
            return STATUS_FAILED
        if self.files and all(f.is_terminal for f in self.files):
            return STATUS_COMPLETED
        return STATUS_QUEUED

    @property
    def completed_count(self) -> int:
        return sum(1 for f in self.files if f.status == STATUS_COMPLETED)

    def file(self, file_id: str) -> JobFile | None:
        return next((f for f in self.files if f.id == file_id), None)


@dataclass
class Session:
    id: str
    token: str
    root: Path
    created_at: datetime
    expires_at: datetime
    jobs: dict[str, Job] = field(default_factory=dict)

    @property
    def uploads(self) -> Path:
        return self.root / "uploads"

    @property
    def working(self) -> Path:
        return self.root / "working"

    @property
    def outputs(self) -> Path:
        return self.root / "outputs"

    def is_expired(self, at: datetime | None = None) -> bool:
        return (at or _now()) >= self.expires_at

    def touch(self, ttl_minutes: int) -> None:
        self.expires_at = _now() + timedelta(minutes=ttl_minutes)


class SessionManager:
    """Owns the lifetime of every session and its workspace directory."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()
        self._root = Path(settings.workspace_root)
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    # --- lifecycle --------------------------------------------------------

    def create(self) -> Session:
        session_id = secrets.token_hex(SESSION_ID_BYTES)
        token = secrets.token_urlsafe(TOKEN_BYTES)
        root = self._root / session_id

        for directory in ("uploads", "working", "outputs"):
            (root / directory).mkdir(parents=True, exist_ok=True)

        session = Session(
            id=session_id,
            token=token,
            root=root,
            created_at=_now(),
            expires_at=_now() + timedelta(minutes=self._settings.session_ttl_minutes),
        )
        with self._lock:
            self._sessions[session_id] = session
        logger.info("session created", extra={"session_id": session_id})
        return session

    def authorize(self, session_id: str, token: str | None) -> Session:
        """Fetch a session, verifying the bearer token in constant time."""
        with self._lock:
            session = self._sessions.get(session_id)

        if session is None or session.is_expired():
            if session is not None:
                self.delete(session_id)
            raise SessionNotFoundError("session missing or expired")

        if not token or not secrets.compare_digest(session.token, token):
            # Same error whether the session is unknown or the token is wrong,
            # so this cannot be used to probe for valid session ids.
            raise NotAuthorizedError("invalid session token")

        session.touch(self._settings.session_ttl_minutes)
        return session

    def delete(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        _remove_tree(session.root)
        logger.info("session deleted", extra={"session_id": session_id})
        return True

    # --- jobs -------------------------------------------------------------

    def create_job(self, session: Session) -> Job:
        job = Job(id=secrets.token_hex(FILE_ID_BYTES), session_id=session.id)
        with self._lock:
            session.jobs[job.id] = job
        return job

    def get_job(self, session: Session, job_id: str) -> Job:
        job = session.jobs.get(job_id)
        if job is None:
            raise SessionNotFoundError("job not found in this session")
        return job

    @staticmethod
    def new_file_id() -> str:
        return secrets.token_hex(FILE_ID_BYTES)

    # --- maintenance ------------------------------------------------------

    def sweep_expired(self) -> int:
        """Delete every expired session. Returns how many were removed."""
        now = _now()
        with self._lock:
            expired = [s.id for s in self._sessions.values() if s.is_expired(now)]
        for session_id in expired:
            self.delete(session_id)
        return len(expired)

    def sweep_orphans(self, max_age_minutes: int | None = None) -> int:
        """Remove workspace directories with no live session behind them.

        This is the crash-recovery path: if the process died holding sessions,
        their directories are still on disk with nothing tracking them.
        """
        max_age = max_age_minutes or (self._settings.session_ttl_minutes * 2)
        cutoff = time.time() - max_age * 60
        removed = 0

        with self._lock:
            known = set(self._sessions)

        try:
            entries = list(self._root.iterdir())
        except FileNotFoundError:
            return 0

        for entry in entries:
            if not entry.is_dir() or entry.name in known:
                continue
            try:
                if entry.stat().st_mtime > cutoff:
                    continue
            except OSError:
                continue
            if _remove_tree(entry):
                removed += 1

        if removed:
            logger.info("removed orphaned workspaces", extra={"count": removed})
        return removed

    def active_session_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def shutdown(self) -> None:
        """Drop every session and its files. Called on process shutdown."""
        with self._lock:
            session_ids = list(self._sessions)
        for session_id in session_ids:
            self.delete(session_id)


def _remove_tree(path: Path) -> bool:
    try:
        shutil.rmtree(path, ignore_errors=True)
        return not path.exists()
    except OSError as exc:  # pragma: no cover - best effort cleanup
        logger.warning("failed to remove workspace", extra={"error_message": str(exc)})
        return False
