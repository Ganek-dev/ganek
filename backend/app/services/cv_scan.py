"""CV virus scanning with an optional ClamAV daemon (board card "CV virus
scanning (ClamAV container)").

Recruiters download CVs that strangers uploaded, so a configured clamd
(``GANEK_CLAMAV_HOST``, compose profile ``clamav``) scans every new upload
in the worker. The flow:

- apply marks the row ``pending`` and enqueues ``scan_cv`` after the commit
  (best-effort; the worker's sweep re-enqueues what redis dropped);
- the worker streams the object to clamd (INSTREAM) and stores ``clean`` or
  ``infected`` plus the signature name;
- an infected CV is never handed out: the download routes answer 409, the
  review link and the DSAR bundle leave the URL out.

Unconfigured, nothing changes: rows keep ``cv_scan_status`` NULL ("not
scanned") and the admin says scanning is not configured. A scanner that
cannot answer parks the row as ``error`` after its retries; the CV stays
downloadable then, because a dead sidecar must not lock every CV away.
"""

import asyncio
import logging
import struct
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import queue
from app.core.config import settings
from app.models import Application, CvScanStatus
from app.services import storage

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 4
RETRY_DELAYS_SECONDS = (30, 120, 600)
# clamd's own StreamMaxLength default is 25 MB; CVs are capped well below
CHUNK_BYTES = 64 * 1024
MAX_SIGNATURE_LENGTH = 200

INFECTED_DETAIL = (
    "The virus scanner flagged this CV, so it cannot be downloaded. "
    "Ask the candidate to upload a new file."
)


class ScanError(Exception):
    """clamd could not give a verdict (unreachable, timeout, ERROR reply)."""


def configured() -> bool:
    return bool(settings.clamav_host)


def initial_status(cv_object_key: str | None) -> CvScanStatus | None:
    """What a new application's CV starts as: pending when there is a CV
    and a scanner, NULL (not scanned) otherwise."""
    if cv_object_key is None or not configured():
        return None
    return CvScanStatus.PENDING


def blocked(application: Application) -> bool:
    """True when the CV must not be handed out."""
    return application.cv_scan_status is CvScanStatus.INFECTED


async def enqueue(application: Application) -> None:
    if application.cv_scan_status is CvScanStatus.PENDING:
        await queue.enqueue("scan_cv", str(application.id), job_id=f"cvscan-{application.id}")


def parse_reply(reply: bytes) -> str | None:
    """None for a clean stream, the signature name for an infected one.

    clamd answers ``stream: OK``, ``stream: <Signature> FOUND`` or
    ``<reason> ERROR``; anything else is treated as an error, never as clean.
    """
    text = reply.rstrip(b"\0\n").decode("utf-8", "replace").strip()
    if text.endswith(" ERROR") or not text:
        raise ScanError(text or "empty reply from clamd")
    _, _, verdict = text.partition(": ")
    if verdict == "OK":
        return None
    if verdict.endswith(" FOUND"):
        signature = verdict.removesuffix(" FOUND").strip() or "unknown"
        return signature[:MAX_SIGNATURE_LENGTH]
    raise ScanError(f"unexpected reply from clamd: {text[:200]}")


async def _instream(data: bytes) -> bytes:
    assert settings.clamav_host is not None
    reader, writer = await asyncio.open_connection(settings.clamav_host, settings.clamav_port)
    try:
        writer.write(b"zINSTREAM\0")
        for offset in range(0, len(data), CHUNK_BYTES):
            chunk = data[offset : offset + CHUNK_BYTES]
            writer.write(struct.pack("!I", len(chunk)) + chunk)
            await writer.drain()
        writer.write(struct.pack("!I", 0))
        await writer.drain()
        return await reader.readuntil(b"\0")
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass


async def scan_bytes(data: bytes) -> str | None:
    """Stream ``data`` to clamd; None when clean, the signature when not."""
    try:
        reply = await asyncio.wait_for(_instream(data), timeout=settings.clamav_timeout_seconds)
    except (OSError, TimeoutError, asyncio.IncompleteReadError) as exc:
        raise ScanError(f"clamd unreachable: {exc.__class__.__name__}: {exc}") from exc
    return parse_reply(reply)


async def scan_application(
    db: AsyncSession, application_id: str | uuid.UUID, *, final: bool = False
) -> CvScanStatus | None:
    """Scan one pending CV and store the verdict. Returns the new status, or
    None when the row was not pending (stale or duplicate job). A ScanError
    propagates for the caller's retry, except on the ``final`` attempt,
    which parks the row as ``error`` instead."""
    application = (
        await db.execute(
            select(Application)
            .where(Application.id == uuid.UUID(str(application_id)))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if application is None or application.cv_scan_status is not CvScanStatus.PENDING:
        return None
    if application.cv_object_key is None:
        application.cv_scan_status = None
        await db.commit()
        return None
    try:
        obj = await storage.get_object(application.cv_object_key)
        if obj is None:
            raise ScanError("CV object not found in storage")
        signature = await scan_bytes(obj[0])
    except ScanError as exc:
        if not final:
            await db.rollback()
            raise
        logger.warning("cv scan for %s gave up: %s", application_id, exc)
        application.cv_scan_status = CvScanStatus.ERROR
        application.cv_scan_signature = None
        application.cv_scanned_at = datetime.now(UTC)
        await db.commit()
        return CvScanStatus.ERROR
    application.cv_scan_status = CvScanStatus.INFECTED if signature else CvScanStatus.CLEAN
    application.cv_scan_signature = signature
    application.cv_scanned_at = datetime.now(UTC)
    await db.commit()
    if signature:
        logger.warning("cv for application %s flagged by clamd: %s", application_id, signature)
    return application.cv_scan_status


async def stuck_scans(db: AsyncSession, *, older_than: datetime) -> list[uuid.UUID]:
    rows = await db.execute(
        select(Application.id).where(
            Application.cv_scan_status == CvScanStatus.PENDING,
            Application.created_at < older_than,
        )
    )
    return list(rows.scalars())
