"""API integration and security tests.

Covers the full journey - upload, convert, poll, read, download, ZIP, clear -
plus the access-control properties that matter for an anonymous public service:
results are reachable only through the session that created them, session
identifiers cannot be guessed or replayed, and no response leaks a server path.
"""

from __future__ import annotations

import io
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.api.deps import Services
from app.main import create_app

TERMINAL = {"completed", "failed", "cancelled"}


@pytest.fixture
def client(settings, monkeypatch):
    """A TestClient wired to the isolated per-test settings."""
    import app.config as config_module

    monkeypatch.setattr(config_module, "get_settings", lambda: settings)
    for module in ("app.main", "app.api.routes"):
        monkeypatch.setattr(f"{module}.get_settings", lambda: settings, raising=False)

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def upload(client, files, **form):
    return client.post("/api/v1/jobs", files=files, data={"ocr_mode": "auto", **form})


def as_upload(name: str, content: bytes, mime: str):
    return ("files", (name, content, mime))


def fixture_upload(fixture, name: str, mime: str = "application/octet-stream"):
    return as_upload(name, fixture(name).read_bytes(), mime)


def wait_for(client, job_id, headers, timeout=90.0):
    deadline = time.monotonic() + timeout
    job = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
        assert response.status_code == 200
        job = response.json()
        if job["status"] in TERMINAL:
            return job
        time.sleep(0.15)
    pytest.fail(f"job did not finish in time: {job}")


def auth(created) -> dict[str, str]:
    return {
        "X-Session-Id": created["session_id"],
        "X-Session-Token": created["session_token"],
    }


CSV = b"Region,Units\nNorth,120\nSouth,340\n"
JSON = b'{"title":"Report","items":[{"n":"a","v":1},{"n":"b","v":2}]}'


# --- health -----------------------------------------------------------------


def test_health_is_cheap_and_does_no_work(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["version"]


def test_ready_reports_dependencies(client):
    body = client.get("/ready").json()
    assert body["status"] in ("ok", "degraded")
    assert body["workspace_writable"] is True
    assert "ocr" in body and "enabled" in body["ocr"]


def test_formats_endpoint_matches_the_registry(client):
    body = client.get("/api/v1/formats").json()
    extensions = {f["extension"] for f in body["formats"]}
    assert {".pdf", ".docx", ".xlsx", ".png", ".zip"} <= extensions
    assert body["limits"]["max_file_size_mb"] > 0


# --- the happy path ---------------------------------------------------------


def test_full_journey_upload_convert_download_cleanup(client):
    created = upload(
        client,
        [as_upload("regions.csv", CSV, "text/csv"),
         as_upload("report.json", JSON, "application/json")],
    ).json()
    headers = auth(created)

    assert created["file_count"] == 2
    assert created["session_id"] and created["session_token"]

    job = wait_for(client, created["id"], headers)
    assert job["status"] == "completed"
    assert job["completed_count"] == 2

    # Read one result.
    file_id = job["files"][0]["id"]
    result = client.get(
        f"/api/v1/jobs/{job['id']}/files/{file_id}", headers=headers
    ).json()
    assert result["markdown"].strip()
    assert result["output_filename"].endswith(".md")
    assert result["metadata"]["word_count"] > 0

    # Download it as a file.
    download = client.get(
        f"/api/v1/jobs/{job['id']}/files/{file_id}/download", headers=headers
    )
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]
    assert download.headers["x-content-type-options"] == "nosniff"

    # Download everything as a ZIP.
    archive = client.post(
        f"/api/v1/jobs/{job['id']}/download", headers=headers, json={"files": []}
    )
    assert archive.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(archive.content)).namelist()
    assert sorted(names) == ["regions.md", "report.md"]

    # Clearing removes everything immediately.
    assert client.delete(
        f"/api/v1/sessions/{created['session_id']}", headers=headers
    ).status_code == 204
    assert client.get(f"/api/v1/jobs/{job['id']}", headers=headers).status_code == 404


def test_zip_download_includes_browser_edits(client):
    created = upload(client, [as_upload("regions.csv", CSV, "text/csv")]).json()
    headers = auth(created)
    job = wait_for(client, created["id"], headers)
    file_id = job["files"][0]["id"]

    edited = "# Edited in the browser\n\nReplaced content.\n"
    archive = client.post(
        f"/api/v1/jobs/{job['id']}/download",
        headers=headers,
        json={"files": [{"id": file_id, "markdown": edited}]},
    )
    with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
        assert bundle.read("regions.md").decode("utf-8") == edited


def test_uploaded_archive_expands_into_separate_results(client, fixture):
    created = upload(
        client, [fixture_upload(fixture, "bundle.zip", "application/zip")]
    ).json()
    headers = auth(created)
    job = wait_for(client, created["id"], headers)

    assert job["status"] == "completed"
    # The one .zip became its two convertible members.
    assert job["file_count"] == 2
    names = {f["filename"] for f in job["files"]}
    assert names == {"table.csv", "records.json"}
    assert all(f["source_archive"] == "bundle.zip" for f in job["files"])


def test_partial_failure_still_returns_the_successes(client):
    created = upload(
        client,
        [
            as_upload("good.csv", CSV, "text/csv"),
            # Valid extension, contents that are not a PDF at all.
            as_upload("bad.pdf", b"this is definitely not a pdf", "application/pdf"),
        ],
    ).json()
    headers = auth(created)
    job = wait_for(client, created["id"], headers)

    statuses = {f["filename"]: f["status"] for f in job["files"]}
    assert statuses["good.csv"] == "completed"
    assert statuses["bad.pdf"] == "failed"
    assert job["completed_count"] == 1

    failed = next(f for f in job["files"] if f["status"] == "failed")
    assert failed["error"]["code"]
    assert failed["error"]["message"]
    assert "Traceback" not in failed["error"]["message"]

    # The successful result is still downloadable.
    archive = client.post(
        f"/api/v1/jobs/{job['id']}/download", headers=headers, json={"files": []}
    )
    assert zipfile.ZipFile(io.BytesIO(archive.content)).namelist() == ["good.md"]


def test_unicode_filenames_survive_the_round_trip(client):
    created = upload(
        client, [as_upload("প্রতিবেদন.csv", CSV, "text/csv")]
    ).json()
    headers = auth(created)
    job = wait_for(client, created["id"], headers)

    assert job["files"][0]["filename"] == "প্রতিবেদন.csv"
    assert job["files"][0]["output_filename"] == "প্রতিবেদন.md"

    download = client.get(
        f"/api/v1/jobs/{job['id']}/files/{job['files'][0]['id']}/download",
        headers=headers,
    )
    disposition = download.headers["content-disposition"]
    # RFC 5987 encoding carries the real name; the ASCII fallback stays valid.
    assert "filename*=UTF-8''" in disposition
    assert 'filename="download.md"' in disposition


def test_retry_reconverts_without_reupload(client):
    created = upload(
        client, [as_upload("bad.pdf", b"not a pdf at all", "application/pdf")]
    ).json()
    headers = auth(created)
    job = wait_for(client, created["id"], headers)
    file_id = job["files"][0]["id"]
    assert job["files"][0]["status"] == "failed"

    response = client.post(
        f"/api/v1/jobs/{job['id']}/files/{file_id}/retry",
        headers=headers,
        data={"ocr_mode": "auto"},
    )
    # The file is retried from the copy still held in the session.
    assert response.status_code == 200
    wait_for(client, job["id"], headers)


def test_cancel_marks_the_job_cancelled(client):
    created = upload(client, [as_upload("regions.csv", CSV, "text/csv")]).json()
    headers = auth(created)
    response = client.post(f"/api/v1/jobs/{created['id']}/cancel", headers=headers)
    assert response.status_code == 200
    job = wait_for(client, created["id"], headers)
    assert job["status"] in TERMINAL


# --- access control ---------------------------------------------------------


def test_results_require_the_session_token(client):
    created = upload(client, [as_upload("regions.csv", CSV, "text/csv")]).json()
    headers = auth(created)
    job = wait_for(client, created["id"], headers)
    file_id = job["files"][0]["id"]

    for bad in (
        {},
        {"X-Session-Id": created["session_id"]},
        {"X-Session-Id": created["session_id"], "X-Session-Token": "wrong-token"},
        {"X-Session-Id": "0" * 32, "X-Session-Token": created["session_token"]},
    ):
        assert client.get(f"/api/v1/jobs/{job['id']}", headers=bad).status_code in (
            403, 404,
        )
        assert client.get(
            f"/api/v1/jobs/{job['id']}/files/{file_id}/download", headers=bad
        ).status_code in (403, 404)


def test_one_session_cannot_read_anothers_results(client):
    first = upload(client, [as_upload("a.csv", CSV, "text/csv")]).json()
    second = upload(client, [as_upload("b.csv", CSV, "text/csv")]).json()
    first_job = wait_for(client, first["id"], auth(first))
    wait_for(client, second["id"], auth(second))

    # Second session's credentials, first session's job id.
    response = client.get(f"/api/v1/jobs/{first_job['id']}", headers=auth(second))
    assert response.status_code == 404

    # Mixing an id from one session with a token from the other must fail.
    mixed = {
        "X-Session-Id": first["session_id"],
        "X-Session-Token": second["session_token"],
    }
    assert client.get(f"/api/v1/jobs/{first_job['id']}", headers=mixed).status_code == 403


def test_session_identifiers_are_unguessable(client):
    seen_ids, seen_tokens = set(), set()
    for _ in range(5):
        created = upload(client, [as_upload("a.csv", CSV, "text/csv")]).json()
        seen_ids.add(created["session_id"])
        seen_tokens.add(created["session_token"])
        assert len(created["session_id"]) >= 32
        assert len(created["session_token"]) >= 32
    assert len(seen_ids) == 5, "session ids must not repeat"
    assert len(seen_tokens) == 5, "tokens must not repeat"


@pytest.mark.parametrize(
    "job_id",
    ["../../../etc/passwd", "..%2F..%2Fetc%2Fpasswd", "%2e%2e%2f", "a/../../b"],
)
def test_path_traversal_in_identifiers_is_refused(client, job_id):
    created = upload(client, [as_upload("a.csv", CSV, "text/csv")]).json()
    headers = auth(created)
    response = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
    assert response.status_code in (400, 404, 422)
    assert b"root:" not in response.content


def test_errors_never_leak_server_paths(client):
    created = upload(
        client, [as_upload("bad.pdf", b"not a pdf", "application/pdf")]
    ).json()
    headers = auth(created)
    job = wait_for(client, created["id"], headers)

    body = str(job)
    for leak in ("/tmp", "C:\\", "workspace", "uploads", "Traceback", "site-packages"):
        assert leak not in body


# --- input validation -------------------------------------------------------


def test_unsupported_file_type_is_rejected(client):
    created = upload(
        client, [as_upload("payload.exe", b"MZ\x90\x00", "application/octet-stream")]
    ).json()
    headers = auth(created)
    job = wait_for(client, created["id"], headers)
    assert job["files"][0]["status"] == "failed"
    assert job["files"][0]["error"]["code"] == "unsupported_format"


def test_mislabelled_file_is_rejected(client, fixture):
    """A PNG renamed to .pdf must not be accepted as a PDF."""
    created = upload(
        client,
        [as_upload("invoice.pdf", fixture("ocr-english.png").read_bytes(), "application/pdf")],
    ).json()
    headers = auth(created)
    job = wait_for(client, created["id"], headers)
    assert job["files"][0]["status"] == "failed"
    assert job["files"][0]["error"]["code"] == "format_mismatch"


def test_oversized_upload_is_refused(client, settings):
    too_big = b"a,b\n" + b"1,2\n" * (settings.max_file_size_bytes // 4 + 1024)
    response = upload(client, [as_upload("huge.csv", too_big, "text/csv")])
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_too_many_files_is_refused(client, settings):
    files = [
        as_upload(f"f{i}.csv", CSV, "text/csv")
        for i in range(settings.max_files_per_job + 3)
    ]
    response = upload(client, files)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "too_many_files"


def test_malicious_filenames_are_sanitized(client):
    created = upload(
        client,
        [
            as_upload("../../etc/passwd.csv", CSV, "text/csv"),
            as_upload("..\\..\\windows\\evil.csv", CSV, "text/csv"),
        ],
    ).json()
    for entry in created["files"]:
        assert "/" not in entry["filename"]
        assert "\\" not in entry["filename"]
        assert ".." not in entry["filename"]


def test_zip_slip_archive_is_refused(client, tmp_path):
    payload = tmp_path / "slip.zip"
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("../../escaped.csv", "a,b\n1,2\n")

    created = upload(
        client, [as_upload("slip.zip", payload.read_bytes(), "application/zip")]
    ).json()
    headers = auth(created)
    job = wait_for(client, created["id"], headers)
    assert job["files"][0]["status"] == "failed"
    assert job["files"][0]["error"]["code"] in ("archive_rejected", "conversion_failed")


def test_script_payload_does_not_survive_html_conversion(client):
    """A hostile .html upload must not yield executable markup downstream.

    Conversion itself drops the script here, and `contains_raw_html` reports
    honestly that nothing dangerous remained. The renderer sanitizes anyway -
    these are independent layers, and this test pins the server-side one.
    """
    html = (
        b"<html><body><h1>Title</h1><script>alert(1)</script>"
        b'<img src=x onerror="alert(2)">'
        b"<p>Real content.</p></body></html>"
    )
    created = upload(client, [as_upload("evil.html", html, "text/html")]).json()
    headers = auth(created)
    job = wait_for(client, created["id"], headers)

    file_id = job["files"][0]["id"]
    result = client.get(
        f"/api/v1/jobs/{job['id']}/files/{file_id}", headers=headers
    ).json()
    markdown = result["markdown"]

    assert "Real content." in markdown, "legitimate content must be preserved"
    assert "<script" not in markdown.lower()
    assert "alert(1)" not in markdown
    assert "onerror" not in markdown.lower()
    # The flag reflects what actually remains, so it must agree with the text.
    assert result["metadata"]["contains_raw_html"] is False


# --- session lifecycle ------------------------------------------------------


def test_expired_sessions_are_swept(client, settings):
    created = upload(client, [as_upload("a.csv", CSV, "text/csv")]).json()
    headers = auth(created)
    wait_for(client, created["id"], headers)

    services: Services = client.app.state.services
    session = services.sessions._sessions[created["session_id"]]
    workspace = session.root
    assert workspace.exists()

    # Force expiry, then run the cleanup sweep the worker runs on a timer.
    from datetime import datetime, timedelta, timezone

    session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    removed = services.cleanup.run_once()

    assert removed["expired_sessions"] >= 1
    assert not workspace.exists(), "workspace directory must be deleted"
    assert client.get(f"/api/v1/jobs/{created['id']}", headers=headers).status_code == 404


def test_orphaned_workspaces_are_reclaimed(client, settings):
    """Crash recovery: directories with no live session behind them."""
    services: Services = client.app.state.services
    orphan = services.sessions.root / "deadbeef00000000"
    orphan.mkdir(parents=True, exist_ok=True)
    (orphan / "leftover.bin").write_bytes(b"stale")

    import os
    import time as time_module

    stale = time_module.time() - settings.session_ttl_minutes * 60 * 4
    os.utime(orphan, (stale, stale))

    assert services.sessions.sweep_orphans() >= 1
    assert not orphan.exists()


def test_uploads_are_removed_after_a_successful_conversion(client):
    created = upload(client, [as_upload("a.csv", CSV, "text/csv")]).json()
    headers = auth(created)
    wait_for(client, created["id"], headers)

    services: Services = client.app.state.services
    session = services.sessions._sessions[created["session_id"]]
    leftover = list(session.uploads.iterdir())
    assert leftover == [], f"uploads should be cleared, found {leftover}"
