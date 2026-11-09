"""CV virus scanning (board card "CV virus scanning (ClamAV container)").

A tiny in-process clamd stand-in speaks the INSTREAM protocol and flags the
EICAR test string, so the whole path (apply, worker scan, download refusal)
runs without a real ClamAV."""

import asyncio
import struct
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from arq import Retry
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app import worker
from app.core import queue
from app.core.config import settings
from app.models import ActivityLog, Application, ApplicationStage, CvScanStatus
from app.services import cv_scan, storage
from tests.db import database_reachable, s3_reachable
from tests.helpers import upload_pdf
from tests.test_applications_api import _submission

# the industry-standard antivirus test file, split so this source file is
# not itself flagged by a scanner on a contributor's machine
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
CLEAN_PDF = b"%PDF-1.4 an ordinary CV"

needs_stack = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)


# --- protocol -----------------------------------------------------------


def test_parse_reply_clean_infected_and_errors() -> None:
    assert cv_scan.parse_reply(b"stream: OK\0") is None
    assert cv_scan.parse_reply(b"stream: Eicar-Test-Signature FOUND\0") == "Eicar-Test-Signature"
    with pytest.raises(cv_scan.ScanError):
        cv_scan.parse_reply(b"INSTREAM size limit exceeded. ERROR\0")
    with pytest.raises(cv_scan.ScanError):
        cv_scan.parse_reply(b"\0")
    # anything unexpected is an error, never "clean"
    with pytest.raises(cv_scan.ScanError):
        cv_scan.parse_reply(b"stream: MAYBE\0")


async def _fake_clamd(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    command = await reader.readuntil(b"\0")
    assert command == b"zINSTREAM\0"
    data = b""
    while True:
        (size,) = struct.unpack("!I", await reader.readexactly(4))
        if size == 0:
            break
        data += await reader.readexactly(size)
    reply = b"stream: Eicar-Test-Signature FOUND\0" if EICAR in data else b"stream: OK\0"
    writer.write(reply)
    await writer.drain()
    writer.close()


@pytest.fixture
async def clamd(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    server = await asyncio.start_server(_fake_clamd, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setattr(settings, "clamav_host", "127.0.0.1")
    monkeypatch.setattr(settings, "clamav_port", port)
    async with server:
        yield
    server.close()


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, tuple[str, ...]]]:
    calls: list[tuple[str, tuple[str, ...]]] = []

    async def _record(function: str, *args: str, **_: Any) -> bool:
        calls.append((function, args))
        return True

    monkeypatch.setattr(queue, "enqueue", _record)
    return calls


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


@pytest.mark.usefixtures("clamd")
async def test_scan_bytes_against_a_clamd() -> None:
    assert await cv_scan.scan_bytes(CLEAN_PDF) is None
    # bigger than one INSTREAM chunk, the signature straddling no boundary
    assert await cv_scan.scan_bytes(b"x" * 200_000 + EICAR) == "Eicar-Test-Signature"


async def test_scan_bytes_unreachable_is_a_scan_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "clamav_host", "127.0.0.1")
    monkeypatch.setattr(settings, "clamav_port", 1)  # nothing listens there
    with pytest.raises(cv_scan.ScanError):
        await cv_scan.scan_bytes(CLEAN_PDF)


# --- end to end -----------------------------------------------------------


async def _apply_with(client: AsyncClient, data: bytes) -> tuple[str, str]:
    """Publish a job, apply with ``data`` as the CV, log the admin back in.
    Returns (application id, admin email)."""
    email = f"scan-admin-{uuid4().hex[:8]}@ganek-ci.dev"
    password = "a-long-secure-password"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"company_name": f"Scan Co {uuid4().hex[:6]}", "email": email, "password": password},
    )
    assert resp.status_code == 201, resp.text
    job = (await client.post("/api/v1/jobs", json={"title": "Backend Engineer"})).json()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    company_slug = (await client.get("/api/v1/company")).json()["slug"]
    await client.post("/api/v1/auth/logout")
    base = f"/api/v1/public/companies/{company_slug}/jobs/{job['slug']}/apply"
    ticket = (await client.post(f"{base}/upload-url")).json()
    assert (await upload_pdf(ticket, data)).is_success
    resp = await client.post(base, json=_submission(ticket["object_key"]))
    assert resp.status_code == 201, resp.text
    assert (
        await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    ).status_code == 200
    items = (await client.get("/api/v1/applications")).json()["items"]
    assert len(items) == 1
    return str(items[0]["id"]), email


async def _status(client: AsyncClient, app_id: str) -> str | None:
    status: str | None = (await client.get(f"/api/v1/applications/{app_id}")).json()[
        "cv_scan_status"
    ]
    return status


async def _run_worker_scan(application_id: str, *, job_try: int = 1) -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        await worker.scan_cv({"session_factory": factory, "job_try": job_try}, application_id)
    finally:
        await engine.dispose()


@needs_stack
@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "clamd")
async def test_eicar_upload_is_flagged_and_cannot_be_downloaded(
    client: AsyncClient, enqueued: list[tuple[str, tuple[str, ...]]]
) -> None:
    app_id, _ = await _apply_with(client, EICAR)
    assert enqueued == [("scan_cv", (app_id,))]
    detail = (await client.get(f"/api/v1/applications/{app_id}")).json()
    assert detail["cv_scan_status"] == "pending"
    assert (await client.get("/api/v1/company")).json()["cv_scanning_configured"] is True

    await _run_worker_scan(app_id)

    detail = (await client.get(f"/api/v1/applications/{app_id}")).json()
    assert detail["cv_scan_status"] == "infected"
    assert detail["cv_scan_signature"] == "Eicar-Test-Signature"
    for path in ("cv-url", "cv"):
        resp = await client.get(f"/api/v1/applications/{app_id}/{path}")
        assert resp.status_code == 409, resp.text
        assert "virus scanner" in resp.json()["detail"]
    # a refused CV is not logged as a download
    log = (await client.get(f"/api/v1/applications/{app_id}/access-log")).json()
    actions = [row["action"] for row in log]
    assert "cv_download" not in actions
    # the DSAR bundle leaves the link out too
    bundle = (await client.get(f"/api/v1/applications/{app_id}/dsar-export")).json()
    assert all(a["cv_download_url"] is None for a in bundle["applications"])

    # a duplicate or stale job is a no-op
    await _run_worker_scan(app_id)
    assert await _status(client, app_id) == "infected"


@needs_stack
@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "clamd")
async def test_clean_upload_is_marked_clean_and_downloads(
    client: AsyncClient, enqueued: list[tuple[str, tuple[str, ...]]]
) -> None:
    app_id, _ = await _apply_with(client, CLEAN_PDF)
    await _run_worker_scan(app_id)
    detail = (await client.get(f"/api/v1/applications/{app_id}")).json()
    assert detail["cv_scan_status"] == "clean"
    assert detail["cv_scan_signature"] is None
    assert (await client.get(f"/api/v1/applications/{app_id}/cv-url")).status_code == 200


@needs_stack
@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_without_a_scanner_uploads_work_and_are_not_scanned(
    client: AsyncClient,
    enqueued: list[tuple[str, tuple[str, ...]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "clamav_host", None)
    app_id, _ = await _apply_with(client, EICAR)
    assert enqueued == []
    detail = (await client.get(f"/api/v1/applications/{app_id}")).json()
    assert detail["cv_scan_status"] is None
    assert (await client.get("/api/v1/company")).json()["cv_scanning_configured"] is False
    assert (await client.get(f"/api/v1/applications/{app_id}/cv-url")).status_code == 200


@needs_stack
@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "clamd")
async def test_scanner_down_retries_then_parks_as_error_and_stays_downloadable(
    client: AsyncClient,
    enqueued: list[tuple[str, tuple[str, ...]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_id, _ = await _apply_with(client, CLEAN_PDF)
    monkeypatch.setattr(settings, "clamav_port", 1)  # the sidecar went away
    with pytest.raises(Retry):
        await _run_worker_scan(app_id, job_try=1)
    assert await _status(client, app_id) == "pending"

    await _run_worker_scan(app_id, job_try=cv_scan.MAX_ATTEMPTS)
    assert await _status(client, app_id) == "error"
    assert (await client.get(f"/api/v1/applications/{app_id}/cv-url")).status_code == 200


@needs_stack
@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "clamd")
async def test_sweep_re_enqueues_old_pending_scans(
    client: AsyncClient, enqueued: list[tuple[str, tuple[str, ...]]]
) -> None:
    app_id, _ = await _apply_with(client, CLEAN_PDF)
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    redis_jobs: list[tuple[str, str]] = []

    class _Redis:
        async def enqueue_job(self, function: str, arg: str) -> None:
            redis_jobs.append((function, arg))

    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        ctx = {"session_factory": factory, "redis": _Redis()}
        await worker.sweep_cv_scans(ctx)
        assert ("scan_cv", app_id) not in redis_jobs  # still fresh
        async with factory() as db:
            await db.execute(
                update(Application)
                .where(Application.id == UUID(app_id))
                .values(created_at=datetime.now(UTC) - timedelta(hours=1))
            )
            await db.commit()
        await worker.sweep_cv_scans(ctx)
        assert ("scan_cv", app_id) in redis_jobs
        async with factory() as db:
            row = await db.get(Application, UUID(app_id))
            assert row is not None and row.cv_scan_status is CvScanStatus.PENDING
    finally:
        await engine.dispose()


# --- candidate re-upload (status page) ------------------------------------


async def _apply_for_reupload(client: AsyncClient, data: bytes) -> dict[str, Any]:
    """Apply with ``data`` as the CV, staying logged in as the admin."""
    email = f"reupload-{uuid4().hex[:8]}@ganek-ci.dev"
    password = "a-long-secure-password"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"company_name": f"Reup Co {uuid4().hex[:6]}", "email": email, "password": password},
    )
    assert resp.status_code == 201, resp.text
    job = (await client.post("/api/v1/jobs", json={"title": "Backend Engineer"})).json()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    slug = (await client.get("/api/v1/company")).json()["slug"]
    base = f"/api/v1/public/companies/{slug}/jobs/{job['slug']}/apply"
    ticket = (await client.post(f"{base}/upload-url")).json()
    assert (await upload_pdf(ticket, data)).is_success
    resp = await client.post(base, json=_submission(ticket["object_key"]))
    assert resp.status_code == 201, resp.text
    token = resp.json()["status_token"]
    app_id = str((await client.get("/api/v1/applications")).json()["items"][0]["id"])
    return {"token": token, "app_id": app_id, "old_key": ticket["object_key"]}


async def _reupload(client: AsyncClient, token: str, data: bytes) -> tuple[int, str]:
    resp = await client.post(f"/api/v1/public/applications/{token}/cv/upload-url")
    assert resp.status_code == 200, resp.text
    ticket = resp.json()
    assert (await upload_pdf(ticket, data)).is_success
    resp = await client.post(
        f"/api/v1/public/applications/{token}/cv",
        json={"cv_object_key": ticket["object_key"], "cv_filename": "new-cv.pdf"},
    )
    return resp.status_code, ticket["object_key"]


@needs_stack
@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "clamd")
async def test_flagged_cv_is_replaced_from_the_status_page_and_scanned_again(
    client: AsyncClient, enqueued: list[tuple[str, tuple[str, ...]]]
) -> None:
    ctx = await _apply_for_reupload(client, EICAR)
    token, app_id = ctx["token"], ctx["app_id"]
    page = f"/api/v1/public/applications/{token}"
    assert (await client.get(page)).json()["cv_reupload_requested"] is False  # still pending

    await _run_worker_scan(app_id)
    status_page = (await client.get(page)).json()
    assert status_page["cv_reupload_requested"] is True
    assert "Eicar" not in str(status_page)  # the signature is for the team only

    code, new_key = await _reupload(client, token, CLEAN_PDF)
    assert code == 200
    assert ("scan_cv", (app_id,)) in enqueued[1:]
    detail = (await client.get(f"/api/v1/applications/{app_id}")).json()
    assert detail["cv_filename"] == "new-cv.pdf"
    assert detail["cv_scan_status"] == "pending"
    assert detail["cv_scan_signature"] is None
    assert (await client.get(page)).json()["cv_reupload_requested"] is False
    # the flagged object is gone, the new one is in place
    assert await storage.stat_object(ctx["old_key"]) is None
    assert await storage.stat_object(new_key) is not None

    await _run_worker_scan(app_id)
    assert (await client.get(f"/api/v1/applications/{app_id}")).json()["cv_scan_status"] == "clean"
    assert (await client.get(f"/api/v1/applications/{app_id}/cv-url")).status_code == 200

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine)() as db:
            rows = (
                (
                    await db.execute(
                        select(ActivityLog).where(
                            ActivityLog.application_id == UUID(app_id),
                            ActivityLog.type == "cv.replaced",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
            assert rows[0].actor_user_id is None
            assert rows[0].payload == {"previous_signature": "Eicar-Test-Signature"}
    finally:
        await engine.dispose()


@needs_stack
@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "clamd")
async def test_a_replacement_that_is_infected_again_is_flagged_again(
    client: AsyncClient, enqueued: list[tuple[str, tuple[str, ...]]]
) -> None:
    ctx = await _apply_for_reupload(client, EICAR)
    await _run_worker_scan(ctx["app_id"])
    code, _ = await _reupload(client, ctx["token"], EICAR)
    assert code == 200
    await _run_worker_scan(ctx["app_id"])
    status_page = (await client.get(f"/api/v1/public/applications/{ctx['token']}")).json()
    assert status_page["cv_reupload_requested"] is True


@needs_stack
@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "clamd")
async def test_a_clean_cv_cannot_be_swapped_through_the_status_link(
    client: AsyncClient, enqueued: list[tuple[str, tuple[str, ...]]]
) -> None:
    ctx = await _apply_for_reupload(client, CLEAN_PDF)
    for _ in range(2):  # pending, then clean
        resp = await client.post(f"/api/v1/public/applications/{ctx['token']}/cv/upload-url")
        assert resp.status_code == 409, resp.text
        resp = await client.post(
            f"/api/v1/public/applications/{ctx['token']}/cv",
            json={"cv_object_key": ctx["old_key"], "cv_filename": "x.pdf"},
        )
        assert resp.status_code == 409, resp.text
        await _run_worker_scan(ctx["app_id"])


@needs_stack
@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "clamd")
async def test_no_reupload_once_the_application_is_closed(
    client: AsyncClient, enqueued: list[tuple[str, tuple[str, ...]]]
) -> None:
    ctx = await _apply_for_reupload(client, EICAR)
    await _run_worker_scan(ctx["app_id"])
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine)() as db:
            await db.execute(
                update(Application)
                .where(Application.id == UUID(ctx["app_id"]))
                .values(stage=ApplicationStage.WITHDRAWN)
            )
            await db.commit()
    finally:
        await engine.dispose()
    page = f"/api/v1/public/applications/{ctx['token']}"
    assert (await client.get(page)).json()["cv_reupload_requested"] is False
    assert (await client.post(f"{page}/cv/upload-url")).status_code == 409


@needs_stack
@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "clamd")
async def test_replacement_must_be_a_new_upload_of_this_company(
    client: AsyncClient, enqueued: list[tuple[str, tuple[str, ...]]]
) -> None:
    ctx = await _apply_for_reupload(client, EICAR)
    await _run_worker_scan(ctx["app_id"])
    url = f"/api/v1/public/applications/{ctx['token']}/cv"
    same = await client.post(url, json={"cv_object_key": ctx["old_key"], "cv_filename": "a.pdf"})
    assert same.status_code == 422, same.text
    foreign = await client.post(
        url, json={"cv_object_key": f"cvs/{uuid4()}/x.pdf", "cv_filename": "a.pdf"}
    )
    assert foreign.status_code == 422, foreign.text
    not_uploaded_key = ctx["old_key"].rsplit("/", 1)[0] + f"/{uuid4().hex}.pdf"
    missing = await client.post(
        url, json={"cv_object_key": not_uploaded_key, "cv_filename": "a.pdf"}
    )
    assert missing.status_code == 422, missing.text
    not_pdf = await client.post(url, json={"cv_object_key": ctx["old_key"], "cv_filename": "a.exe"})
    assert not_pdf.status_code == 422, not_pdf.text
