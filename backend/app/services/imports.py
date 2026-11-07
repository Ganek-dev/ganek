"""CSV import of candidates into a job (people already in an ATS or a sheet).

The browser parses the file and maps the columns; this service gets plain
rows (name, email, optional source) plus one free-text ``origin`` naming
where the data came from. Every new person becomes an application without
a CV (0046) and gets the job's assessment invite, or the confirmation when
the job has no assessment, with the GDPR art. 14 paragraph naming the
origin: the candidate never saw our privacy notice before this mail.

Dedupe is by email per company, case-insensitive: anyone the workspace
already has as a candidate (any job) and any repeat inside the file is
skipped and counted, never re-mailed. Rows without a usable name or email
are counted as invalid. A dry run answers the same counts without writing,
which is the preview. One ``applications.imported`` activity entry records
who imported how many; the per-row received entries are marked bulk.

Out of scope (card): pulling from an ATS API, importing scores or notes,
auto-reject.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import urls
from app.core.security import create_quiz_token
from app.core.sources import normalize_source
from app.models import Application, Candidate, Company, Job
from app.schemas.public import ApplicationSubmit
from app.services import activity, outbox
from app.services import applications as applications_service
from app.services import company as company_service
from app.services import quiz as quiz_service

MAX_ROWS = 1000
# the stored source when a row names none the source grammar accepts
IMPORT_SOURCE = "link:import"


@dataclass(frozen=True)
class ImportRow:
    name: str
    email: str
    source: str | None = None


@dataclass
class ImportResult:
    imported: int = 0
    duplicates: int = 0
    invalid: int = 0
    # the 1-based row numbers of each skip, so the preview can point at them
    duplicate_rows: list[int] = field(default_factory=list)
    invalid_rows: list[int] = field(default_factory=list)
    application_ids: list[uuid.UUID] = field(default_factory=list)


def _payload(row: ImportRow) -> ApplicationSubmit | None:
    name = " ".join(row.name.split())
    email = row.email.strip()
    if not name or not email:
        return None
    try:
        payload = ApplicationSubmit(name=name, email=email, source=row.source)
    except ValidationError:
        return None
    if normalize_source(payload.source) is None:
        payload.source = IMPORT_SOURCE
    return payload


async def _known_emails(db: AsyncSession, company: Company, emails: set[str]) -> set[str]:
    if not emails:
        return set()
    rows = await db.execute(
        select(func.lower(Candidate.email)).where(
            Candidate.company_id == company.id, func.lower(Candidate.email).in_(emails)
        )
    )
    return set(rows.scalars().all())


async def _plan(
    db: AsyncSession, company: Company, rows: list[ImportRow]
) -> tuple[ImportResult, list[ApplicationSubmit]]:
    result = ImportResult()
    parsed = [_payload(row) for row in rows]
    known = await _known_emails(db, company, {p.email.lower() for p in parsed if p is not None})
    seen: set[str] = set()
    fresh: list[ApplicationSubmit] = []
    for number, payload in enumerate(parsed, start=1):
        if payload is None:
            result.invalid += 1
            result.invalid_rows.append(number)
            continue
        key = payload.email.lower()
        if key in known or key in seen:
            result.duplicates += 1
            result.duplicate_rows.append(number)
            continue
        seen.add(key)
        fresh.append(payload)
    return result, fresh


async def _send_invite(
    db: AsyncSession,
    company: Company,
    job: Job,
    application: Application,
    payload: ApplicationSubmit,
    origin: str,
) -> None:
    """The same mail the public apply sends (quiz invite, or the
    confirmation without an assessment), plus the data-origin paragraph."""
    common: dict[str, Any] = {
        "to": payload.email,
        "ref": str(application.id),
        "candidate_name": payload.name,
        "job_title": job.title,
        "company_name": company.name,
        "controller_name": company_service.controller_name(company),
        "privacy_url": urls.privacy_notice_url(company),
        "data_origin": origin,
    }
    attempt = await quiz_service.create_attempt(db, company, application, job)
    if attempt is not None:
        await outbox.queue_email(
            db,
            kind="quiz_invite",
            company_id=company.id,
            application_id=application.id,
            brand_primary=(company.theme or {}).get("primary_color"),
            quiz_url=urls.quiz_url(company, create_quiz_token(attempt.id)),
            question_count=len(attempt.question_ids),
            seconds_per_question=quiz_service.seconds_per_question(attempt),
            expires_at=attempt.expires_at,
            **common,
        )
    else:
        await outbox.queue_email(
            db,
            kind="application_received",
            company_id=company.id,
            application_id=application.id,
            **common,
        )


async def import_candidates(
    db: AsyncSession,
    company: Company,
    job: Job,
    rows: list[ImportRow],
    *,
    origin: str,
    actor_user_id: uuid.UUID | None,
    dry_run: bool = False,
) -> ImportResult:
    """Create an application and send the invite for every new person in
    ``rows``; count the duplicates and invalid rows. ``dry_run`` only counts."""
    result, fresh = await _plan(db, company, rows)
    if dry_run:
        result.imported = len(fresh)
        return result
    for payload in fresh:
        try:
            application = await applications_service.submit_application(
                db, company, job, payload, allow_missing_cv=True, imported=True
            )
        except applications_service.AlreadyAppliedError:
            # a candidate applied between the plan and this row
            result.duplicates += 1
            continue
        result.imported += 1
        result.application_ids.append(application.id)
        await _send_invite(db, company, job, application, payload, origin)
    activity.record(
        db,
        company_id=company.id,
        type=activity.APPLICATIONS_IMPORTED,
        actor_user_id=actor_user_id,
        payload={
            "job": job.title,
            "count": result.imported,
            "duplicates": result.duplicates,
            "invalid": result.invalid,
            "origin": origin,
        },
    )
    await db.commit()
    return result
