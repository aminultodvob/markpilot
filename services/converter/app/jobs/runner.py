"""Job execution.

Conversions run on a bounded thread pool rather than on the event loop, since
parsing and OCR are CPU-bound and would otherwise block every other request.
The pool size caps how much work the service will do at once, which is the
main defence against CPU and memory exhaustion.

Timeouts and cancellation are *cooperative*: the engine and the OCR page loop
check a callback at each step and abandon the work when it returns true. A
thread cannot be killed safely in Python, so a parser stuck inside a single C
call will still finish that call - the file-size and page limits exist to bound
how long that can be.

Archives are expanded here rather than in the engine: one uploaded .zip becomes
many result rows, which is a job-level concern.
"""

from __future__ import annotations

import contextlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.config import Settings
from app.conversion.engine import ArchiveMarker, ConversionEngine, ConversionOptions
from app.conversion.errors import ConversionError, ConversionTimeoutError
from app.logging_setup import get_logger
from app.security.archive import extract_entry, inspect_archive
from app.security.filenames import dedupe_name, sanitize_filename
from app.sessions.manager import (
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PROCESSING,
    Job,
    JobFile,
    Session,
    SessionManager,
)

logger = get_logger(__name__)


class JobRunner:
    def __init__(
        self,
        settings: Settings,
        engine: ConversionEngine,
        sessions: SessionManager,
    ) -> None:
        self._settings = settings
        self._engine = engine
        self._sessions = sessions
        self._pool = ThreadPoolExecutor(
            max_workers=max(settings.max_concurrent_conversions, 1),
            thread_name_prefix="convert",
        )
        self._lock = threading.Lock()

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    # --- submission -------------------------------------------------------

    def submit(self, session: Session, job: Job, options: ConversionOptions) -> None:
        """Queue every file in the job. Returns immediately."""
        for job_file in list(job.files):
            self._pool.submit(self._process, session, job, job_file, options)

    def cancel(self, job: Job) -> int:
        """Mark a job cancelled. Returns how many files were still running."""
        job.cancelled = True
        affected = 0
        for job_file in job.files:
            if not job_file.is_terminal:
                affected += 1
                if job_file.status != STATUS_PROCESSING:
                    # Queued work never starts; running work stops at its next
                    # checkpoint and marks itself.
                    job_file.status = STATUS_CANCELLED
                    job_file.stage = None
        return affected

    def retry(
        self, session: Session, job: Job, job_file: JobFile, options: ConversionOptions
    ) -> bool:
        """Re-run a failed file from the copy still in the session workspace."""
        if job_file.stored_path is None or not job_file.stored_path.exists():
            return False
        job.cancelled = False
        job_file.status = STATUS_PROCESSING
        job_file.stage = None
        job_file.error_code = None
        job_file.error_message = None
        job_file.error_detail = None
        job_file.markdown = None
        job_file.result = None
        self._pool.submit(self._process, session, job, job_file, options)
        return True

    # --- execution --------------------------------------------------------

    def _process(
        self,
        session: Session,
        job: Job,
        job_file: JobFile,
        options: ConversionOptions,
    ) -> None:
        if job.cancelled:
            job_file.status = STATUS_CANCELLED
            return

        deadline = time.monotonic() + self._settings.max_conversion_time_seconds

        def should_cancel() -> bool:
            return job.cancelled or time.monotonic() > deadline

        job_file.status = STATUS_PROCESSING
        started = time.monotonic()

        try:
            if job_file.stored_path is None:
                raise ConversionError("upload is missing from the workspace")

            outcome = self._engine.convert(
                job_file.stored_path,
                filename=job_file.filename,
                options=options,
                workdir=session.working,
                should_cancel=should_cancel,
                on_stage=lambda stage: setattr(job_file, "stage", stage),
            )

            if isinstance(outcome, ArchiveMarker):
                self._expand_archive(session, job, job_file, options)
                return

            job_file.markdown = outcome.markdown
            job_file.result = outcome
            job_file.status = STATUS_COMPLETED
            job_file.stage = None

            logger.info(
                "conversion completed",
                extra={
                    "format": outcome.metadata.format,
                    "source_bytes": outcome.metadata.source_bytes,
                    "duration_ms": outcome.metadata.duration_ms,
                    "ocr_used": outcome.metadata.ocr_used,
                    "word_count": outcome.metadata.word_count,
                },
            )

        except ConversionError as exc:
            self._fail(job_file, exc, job, started)
        except Exception as exc:
            logger.error(
                "unexpected conversion failure",
                extra={"error_type": type(exc).__name__},
                exc_info=True,
            )
            self._fail(job_file, ConversionError(str(exc)), job, started)
        finally:
            # The upload is no longer needed once the file reached a terminal
            # state, unless it may still be retried.
            if job_file.status == STATUS_COMPLETED:
                self._discard_upload(job_file)

    def _fail(
        self, job_file: JobFile, error: ConversionError, job: Job, started: float
    ) -> None:
        elapsed = time.monotonic() - started
        if job.cancelled:
            job_file.status = STATUS_CANCELLED
            job_file.stage = None
            return

        if elapsed >= self._settings.max_conversion_time_seconds:
            error = ConversionTimeoutError(str(error))

        job_file.status = STATUS_FAILED
        job_file.stage = None
        job_file.error_code = error.code
        job_file.error_message = error.message
        job_file.error_detail = error.detail
        logger.info(
            "conversion failed",
            extra={
                "error_category": error.code,
                "duration_ms": int(elapsed * 1000),
            },
        )

    def _discard_upload(self, job_file: JobFile) -> None:
        path = job_file.stored_path
        if path is None:
            return
        with contextlib.suppress(OSError):  # best effort
            path.unlink(missing_ok=True)
        job_file.stored_path = None

    # --- archives ---------------------------------------------------------

    def _expand_archive(
        self,
        session: Session,
        job: Job,
        archive_file: JobFile,
        options: ConversionOptions,
    ) -> None:
        """Replace an archive row with one row per convertible member."""
        assert archive_file.stored_path is not None
        inspection = inspect_archive(archive_file.stored_path, self._settings)
        convertible = inspection.convertible

        if not convertible:
            raise ConversionError(
                "archive contains no supported files",
                message="This archive doesn't contain any files we can convert.",
            )

        destination = session.working / f"archive-{archive_file.id}"
        destination.mkdir(parents=True, exist_ok=True)

        taken = {f.filename for f in job.files}
        new_files: list[JobFile] = []

        for entry in convertible:
            extracted = extract_entry(
                archive_file.stored_path, entry, destination, self._settings
            )
            display = dedupe_name(sanitize_filename(entry.display_name), taken)
            taken.add(display)
            new_files.append(
                JobFile(
                    id=self._sessions.new_file_id(),
                    filename=display,
                    size=extracted.stat().st_size,
                    source_archive=archive_file.filename,
                    stored_path=extracted,
                )
            )

        with self._lock:
            index = job.files.index(archive_file)
            job.files[index : index + 1] = new_files

        if inspection.skipped:
            logger.info(
                "archive entries skipped",
                extra={"skipped_count": len(inspection.skipped)},
            )

        self._discard_upload(archive_file)
        for new_file in new_files:
            self._pool.submit(self._process, session, job, new_file, options)
