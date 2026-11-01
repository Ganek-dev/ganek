"""Outbound webhooks (card D4, part B).

Endpoints are admin-registered public HTTPS URLs subscribed to a subset
of EVENTS. An event writes one ``WebhookDelivery`` row per subscribed
endpoint right after the causing transaction commits, then hands the id
to arq. The worker POSTs a JSON envelope signed with HMAC-SHA256 over
``"<unix ts>.<body>"`` (header ``X-Ganek-Signature: sha256=<hex>``),
retries with backoff and parks the row as ``failed`` after MAX_ATTEMPTS.
Redis being down only delays: ``stuck_deliveries`` feeds the sweeper.

Payloads carry the same summary the admin list shows: never answers,
never ``correct_key``, never the raw integrity event stream. They are
additive v2: besides the v1 keys they hold a split name, links, the cover
message, absolute job and admin URLs and a one-line quiz summary, enough
for a Zapier recipe to create a candidate in an ATS from one delivery.
"""

import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import queue, urls
from app.core.crypto import decrypt_secret, encrypt_secret
from app.models import Application, Company, User
from app.models.quiz import AttemptStatus, QuizAttempt
from app.models.webhook import DeliveryStatus, WebhookDelivery, WebhookEndpoint
from app.services import activity
from app.services.names import split_name

logger = logging.getLogger(__name__)

EVENTS = ("application.created", "stage.changed", "quiz.completed")
PING = "ping"
HOOK_PREFIX = "whsec_"
MAX_ATTEMPTS = 5
RETRY_DELAYS_SECONDS = (60, 300, 900, 3600)
TIMEOUT_SECONDS = 10
MAX_ERROR_LENGTH = 500


class InvalidUrl(ValueError):
    """Not a public https URL (SSRF guard for admin-supplied targets)."""


class DeliveryError(Exception):
    """One failed attempt: non-2xx status or a transport problem."""


# --- validation + crypto ---------------------------------------------------


def validate_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = parts.hostname
    if parts.scheme != "https" or not host:
        raise InvalidUrl("Webhook URLs must be https:// and name a host")
    if host == "localhost" or host.endswith(".localhost"):
        raise InvalidUrl("Webhook URLs must point at a public host")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return url.strip()  # a DNS name; resolution is the deployment's business
    if not address.is_global:
        raise InvalidUrl("Webhook URLs must point at a public address")
    return url.strip()


def sign(secret: str, timestamp: int, body: bytes) -> str:
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"sha256={digest.hexdigest()}"


def new_endpoint(
    company: Company, *, name: str, url: str, events: list[str]
) -> tuple[WebhookEndpoint, str]:
    """An unsaved endpoint plus its one-time secret."""
    secret = HOOK_PREFIX + secrets.token_urlsafe(32)
    endpoint = WebhookEndpoint(
        company_id=company.id,
        name=name,
        url=validate_url(url),
        secret_enc=encrypt_secret(secret),
        events=list(events),
    )
    return endpoint, secret


# --- admin operations ------------------------------------------------------


async def create_endpoint(
    db: AsyncSession, company: Company, *, name: str, url: str, events: list[str], actor: User
) -> tuple[WebhookEndpoint, str]:
    endpoint, secret = new_endpoint(company, name=name, url=url, events=events)
    endpoint.created_by_user_id = actor.id
    db.add(endpoint)
    await db.flush()
    activity.record(
        db,
        company_id=company.id,
        type=activity.WEBHOOK_CREATED,
        actor_user_id=actor.id,
        payload={"name": name, "url": endpoint.url, "events": list(events)},
    )
    await db.commit()
    await db.refresh(endpoint)
    return endpoint, secret


async def get_endpoint(
    db: AsyncSession, company: Company, endpoint_id: uuid.UUID
) -> WebhookEndpoint | None:
    return (
        await db.execute(
            select(WebhookEndpoint).where(
                WebhookEndpoint.id == endpoint_id, WebhookEndpoint.company_id == company.id
            )
        )
    ).scalar_one_or_none()


async def list_endpoints(
    db: AsyncSession, company: Company
) -> list[tuple[WebhookEndpoint, WebhookDelivery | None]]:
    """Endpoints newest first, each with its most recent delivery."""
    endpoints = (
        (
            await db.execute(
                select(WebhookEndpoint)
                .where(WebhookEndpoint.company_id == company.id)
                .order_by(WebhookEndpoint.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    out: list[tuple[WebhookEndpoint, WebhookDelivery | None]] = []
    for endpoint in endpoints:
        last = (
            await db.execute(
                select(WebhookDelivery)
                .where(WebhookDelivery.endpoint_id == endpoint.id)
                .order_by(WebhookDelivery.created_at.desc(), WebhookDelivery.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        out.append((endpoint, last))
    return out


async def delete_endpoint(
    db: AsyncSession, company: Company, endpoint_id: uuid.UUID, *, actor: User
) -> bool:
    endpoint = await get_endpoint(db, company, endpoint_id)
    if endpoint is None:
        return False
    activity.record(
        db,
        company_id=company.id,
        type=activity.WEBHOOK_DELETED,
        actor_user_id=actor.id,
        payload={"name": endpoint.name, "url": endpoint.url},
    )
    await db.delete(endpoint)  # deliveries cascade
    await db.commit()
    return True


async def list_deliveries(
    db: AsyncSession, company: Company, endpoint_id: uuid.UUID, *, limit: int = 20
) -> list[WebhookDelivery] | None:
    if await get_endpoint(db, company, endpoint_id) is None:
        return None
    rows = await db.execute(
        select(WebhookDelivery)
        .where(WebhookDelivery.endpoint_id == endpoint_id)
        .order_by(WebhookDelivery.created_at.desc(), WebhookDelivery.id.desc())
        .limit(limit)
    )
    return list(rows.scalars().all())


async def queue_test(
    db: AsyncSession, company: Company, endpoint_id: uuid.UUID
) -> WebhookDelivery | None:
    """A ``ping`` delivery so admins can prove the receiver and signature."""
    endpoint = await get_endpoint(db, company, endpoint_id)
    if endpoint is None:
        return None
    rows = await _queue(
        db,
        company_id=company.id,
        endpoints=[endpoint],
        event=PING,
        data={"endpoint": endpoint.name, "message": "Test delivery from Ganek"},
    )
    return rows[0]


# --- payloads + emission ---------------------------------------------------


def quiz_summary(attempt: QuizAttempt) -> str:
    """One readable line about the screening, for a note field in an ATS."""
    if (
        attempt.status is AttemptStatus.COMPLETED
        and attempt.score is not None
        and attempt.completed_at is not None
    ):
        count = len(attempt.integrity.get("flags", []))
        notes = "no integrity notes" if count == 0 else f"{count} integrity note"
        if count > 1:
            notes += "s"
        return (
            f"Ganek screening: {round(attempt.score * 100)}% ({len(attempt.question_ids)} "
            f"questions), completed {attempt.completed_at.date().isoformat()}, {notes}"
        )
    return f"Ganek screening: not completed (status {attempt.status.value})"


def application_payload(application: Application, company: Company) -> dict[str, Any]:
    """Summary-level view of one application, candidate and job loaded."""
    attempt = application.quiz_attempt
    quiz: dict[str, Any] | None = None
    if attempt is not None:
        quiz = {
            "status": attempt.status.value,
            "score_percent": round(attempt.score * 100) if attempt.score is not None else None,
            "completed_at": attempt.completed_at.isoformat() if attempt.completed_at else None,
            "flags": [str(flag.get("summary", "")) for flag in attempt.integrity.get("flags", [])],
            "summary": quiz_summary(attempt),
        }
    candidate = application.candidate
    first_name, last_name = split_name(candidate.name)
    created_at = application.created_at.isoformat() if application.created_at else None
    return {
        "id": str(application.id),
        "stage": application.stage.value,
        "source": application.source,
        "created_at": created_at,
        "applied_at": created_at,
        "message": application.message,
        "admin_url": urls.admin_applicant_url(company, application.id),
        "candidate": {
            "name": candidate.name,
            "first_name": first_name,
            "last_name": last_name,
            "email": candidate.email,
            "links": {key: candidate.links.get(key) for key in ("github", "linkedin", "portfolio")},
        },
        "job": {
            "id": str(application.job.id),
            "title": application.job.title,
            "slug": application.job.slug,
            "public_url": urls.job_url(company, application.job.slug),
        },
        "quiz": quiz,
    }


async def emit_application_event(
    db: AsyncSession,
    application_id: uuid.UUID,
    event: str,
    extra: dict[str, Any] | None = None,
) -> list[WebhookDelivery]:
    """Fan one application event out to the subscribed endpoints. Loads the
    application fresh (callers have usually just committed) and commits
    the delivery rows; redis being down leaves them for the sweeper."""
    application = (
        await db.execute(
            select(Application)
            .where(Application.id == application_id)
            .options(
                selectinload(Application.candidate),
                selectinload(Application.job),
                selectinload(Application.quiz_attempts),
            )
        )
    ).scalar_one_or_none()
    if application is None:
        return []
    endpoints = (
        (
            await db.execute(
                select(WebhookEndpoint).where(
                    WebhookEndpoint.company_id == application.company_id,
                    WebhookEndpoint.is_active.is_(True),
                    WebhookEndpoint.events.contains([event]),
                )
            )
        )
        .scalars()
        .all()
    )
    if not endpoints:
        return []
    company = await db.get(Company, application.company_id)
    assert company is not None
    data = application_payload(application, company)
    if extra:
        data.update(extra)
    return await _queue(
        db, company_id=application.company_id, endpoints=list(endpoints), event=event, data=data
    )


async def _queue(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    endpoints: list[WebhookEndpoint],
    event: str,
    data: dict[str, Any],
) -> list[WebhookDelivery]:
    rows = [
        WebhookDelivery(
            company_id=company_id,
            endpoint_id=endpoint.id,
            event=event,
            payload={"event": event, "data": data},
        )
        for endpoint in endpoints
    ]
    db.add_all(rows)
    await db.commit()
    for row in rows:
        await db.refresh(row)
        await queue.enqueue("deliver_webhook", str(row.id), job_id=f"webhook-{row.id}")
    return rows


# --- delivery (worker side) -----------------------------------------------


def _http_post(url: str, body: bytes, headers: dict[str, str]) -> int:
    """POST and return the HTTP status; tests replace this. Transport
    problems raise DeliveryError; any status comes back for the caller to
    judge (a 4xx is as final as a 5xx for the retry loop)."""
    request = urllib.request.Request(url, data=body, method="POST", headers=headers)  # noqa: S310 - https enforced at create time
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except (urllib.error.URLError, OSError) as exc:
        raise DeliveryError(str(exc.reason if hasattr(exc, "reason") else exc)) from exc


def envelope(delivery: WebhookDelivery) -> bytes:
    body = {
        "id": str(delivery.id),
        "event": delivery.event,
        "created_at": delivery.created_at.isoformat() if delivery.created_at else None,
        "data": delivery.payload.get("data", {}),
    }
    return json.dumps(body, separators=(",", ":"), sort_keys=True).encode()


async def deliver(db: AsyncSession, delivery: WebhookDelivery) -> None:
    """One attempt: sign, POST, judge. Raises DeliveryError on anything
    but a 2xx; the worker owns the attempt counter and the retry."""
    endpoint = await db.get(WebhookEndpoint, delivery.endpoint_id)
    if endpoint is None or not endpoint.is_active:
        raise DeliveryError("endpoint removed or inactive")
    secret = decrypt_secret(endpoint.secret_enc)
    if secret is None:
        raise DeliveryError("endpoint secret unreadable (encryption key rotated?)")
    body = envelope(delivery)
    timestamp = int(time.time())
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Ganek-Webhooks/1",
        "X-Ganek-Event": delivery.event,
        "X-Ganek-Delivery": str(delivery.id),
        "X-Ganek-Timestamp": str(timestamp),
        "X-Ganek-Signature": sign(secret, timestamp, body),
    }
    status = _http_post(endpoint.url, body, headers)
    delivery.response_status = status
    if not 200 <= status < 300:
        raise DeliveryError(f"HTTP {status}")
    delivery.status = DeliveryStatus.DELIVERED
    delivery.delivered_at = datetime.now(UTC)
    delivery.last_error = None


async def stuck_deliveries(
    db: AsyncSession, *, older_than: datetime, limit: int = 200
) -> list[uuid.UUID]:
    rows = await db.execute(
        select(WebhookDelivery.id)
        .where(
            WebhookDelivery.status == DeliveryStatus.QUEUED,
            WebhookDelivery.updated_at < older_than,
        )
        .order_by(WebhookDelivery.created_at)
        .limit(limit)
    )
    return list(rows.scalars().all())
