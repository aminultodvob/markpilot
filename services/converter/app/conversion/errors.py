"""Error taxonomy for the converter service.

Every failure the user can trigger maps to one of these, so the API can return
a stable machine-readable ``code`` plus a human sentence that never leaks a
stack trace or a server path.
"""

from __future__ import annotations


class ConversionError(Exception):
    """Base class for all expected, user-facing failures."""

    code = "conversion_failed"
    http_status = 400
    message = "We couldn't convert this file."

    def __init__(self, detail: str | None = None, *, message: str | None = None):
        self.detail = detail
        if message:
            self.message = message
        super().__init__(detail or self.message)


class UnsupportedFormatError(ConversionError):
    code = "unsupported_format"
    http_status = 415
    message = "This file type isn't supported yet."


class FormatMismatchError(ConversionError):
    code = "format_mismatch"
    http_status = 415
    message = "This file's contents don't match its extension."


class CorruptFileError(ConversionError):
    code = "corrupt_file"
    message = "This file appears to be damaged or unreadable."


class FileTooLargeError(ConversionError):
    code = "file_too_large"
    http_status = 413
    message = "This file is larger than the upload limit."


class TooManyFilesError(ConversionError):
    code = "too_many_files"
    http_status = 413
    message = "That's more files than a single job allows."


class ArchiveError(ConversionError):
    code = "archive_rejected"
    message = "This archive couldn't be processed safely."


class ConversionTimeoutError(ConversionError):
    code = "timeout"
    http_status = 504
    message = "This file took too long to convert."


class ConversionCancelledError(ConversionError):
    code = "cancelled"
    http_status = 409
    message = "This conversion was cancelled."


class OcrUnavailableError(ConversionError):
    code = "ocr_unavailable"
    http_status = 503
    message = "This document needs OCR, which isn't available right now."


class EmptyResultError(ConversionError):
    code = "empty_result"
    message = "We couldn't find any readable content in this file."


class SessionNotFoundError(ConversionError):
    code = "session_not_found"
    http_status = 404
    message = "This session has expired. Please upload your files again."


class NotAuthorizedError(ConversionError):
    code = "not_authorized"
    http_status = 403
    message = "You don't have access to this resource."


class RateLimitedError(ConversionError):
    code = "rate_limited"
    http_status = 429
    message = "You've made a lot of requests. Please try again shortly."
