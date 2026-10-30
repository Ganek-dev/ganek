"""Workspace email templates (card "Candidate emails", PR 3): CRUD under
the tenancy, one default per kind, the cap, and ``resolve`` - the one
place that decides which subject and body a stage mail renders from."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import urls
from app.models import Company, EmailTemplate, Job, JobStatus
from app.services import company as company_service
from app.services import email_render
from app.services.email_render import Template

KIND_LABELS: dict[str, str] = {
    "quiz_invite": "Assessment invite",
    "quiz_reminder": "Assessment reminder",
    "stage_advance": "Interview",
    "rejection": "Rejection",
}
CAP_PER_KIND = 20
BUILTIN_ID: Literal["builtin"] = "builtin"
# the recruiter's preview never holds a candidate's signed link
PREVIEW_LINK_PLACEHOLDER = "personal-link"
SAMPLE_CANDIDATE = "Alex Example"
SAMPLE_JOB_TITLE = "Backend Engineer"

TemplateRef = uuid.UUID | Literal["builtin"] | None


class NotFound(Exception):
    """No template with that id in this workspace."""


class CapReached(Exception):
    """The workspace already has the maximum number of templates of this kind."""


class InvalidTemplate(ValueError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def clean(kind: str, name: str | None, subject: str, body: str) -> tuple[str | None, str, str]:
    if kind not in email_render.KINDS:
        raise InvalidTemplate("Unknown email kind")
    cleaned_name = name.strip() if name is not None else None
    if cleaned_name is not None and not cleaned_name:
        raise InvalidTemplate("Name is required")
    subject, body = subject.strip(), body.strip()
    if not subject:
        raise InvalidTemplate("Subject is required")
    if "\n" in subject or "\r" in subject:
        # a header line break makes the transport refuse every mail of the kind
        raise InvalidTemplate("Subject must be one line")
    if not body:
        raise InvalidTemplate("Body is required")
    try:
        email_render.validate(kind, subject, body)
    except email_render.TemplateError as exc:
        label = "placeholder" if len(exc.placeholders) == 1 else "placeholders"
        raise InvalidTemplate(f"Unknown {label}: {', '.join(exc.placeholders)}") from None
    return cleaned_name, subject, body


async def list_for(db: AsyncSession, company: Company) -> list[EmailTemplate]:
    rows = await db.execute(
        select(EmailTemplate)
        .where(EmailTemplate.company_id == company.id)
        .order_by(EmailTemplate.kind, EmailTemplate.created_at, EmailTemplate.id)
    )
    return list(rows.scalars().all())


async def _get(db: AsyncSession, company: Company, template_id: uuid.UUID) -> EmailTemplate:
    row = (
        await db.execute(
            select(EmailTemplate).where(
                EmailTemplate.company_id == company.id, EmailTemplate.id == template_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound
    return row


async def create(
    db: AsyncSession,
    company: Company,
    *,
    kind: str,
    name: str,
    subject: str,
    body: str,
    actor_user_id: uuid.UUID | None,
) -> EmailTemplate:
    cleaned_name, subject, body = clean(kind, name, subject, body)
    assert cleaned_name is not None
    count = (
        await db.execute(
            select(func.count())
            .select_from(EmailTemplate)
            .where(EmailTemplate.company_id == company.id, EmailTemplate.kind == kind)
        )
    ).scalar_one()
    if count >= CAP_PER_KIND:
        raise CapReached
    row = EmailTemplate(
        company_id=company.id,
        kind=kind,
        name=cleaned_name,
        subject=subject,
        body=body,
        created_by_user_id=actor_user_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def update_template(
    db: AsyncSession,
    company: Company,
    template_id: uuid.UUID,
    *,
    name: str | None = None,
    subject: str | None = None,
    body: str | None = None,
) -> EmailTemplate:
    row = await _get(db, company, template_id)
    cleaned_name, subject, body = clean(
        row.kind,
        name if name is not None else row.name,
        subject if subject is not None else row.subject,
        body if body is not None else row.body,
    )
    assert cleaned_name is not None
    row.name, row.subject, row.body = cleaned_name, subject, body
    await db.commit()
    await db.refresh(row)
    return row


async def delete(db: AsyncSession, company: Company, template_id: uuid.UUID) -> None:
    row = await _get(db, company, template_id)
    await db.delete(row)
    await db.commit()


async def set_default(db: AsyncSession, company: Company, template_id: uuid.UUID) -> EmailTemplate:
    """One default per kind: the others lose the flag in the same transaction
    (the partial unique index would otherwise refuse the second)."""
    row = await _get(db, company, template_id)
    await db.execute(
        update(EmailTemplate)
        .where(
            EmailTemplate.company_id == company.id,
            EmailTemplate.kind == row.kind,
            EmailTemplate.is_default.is_(True),
            EmailTemplate.id != row.id,
        )
        .values(is_default=False)
    )
    row.is_default = True
    await db.commit()
    await db.refresh(row)
    return row


async def clear_default(db: AsyncSession, company: Company, kind: str) -> None:
    """Back to the Ganek default for a kind: no row keeps the flag."""
    if kind not in email_render.KINDS:
        raise InvalidTemplate("Unknown email kind")
    await db.execute(
        update(EmailTemplate)
        .where(
            EmailTemplate.company_id == company.id,
            EmailTemplate.kind == kind,
            EmailTemplate.is_default.is_(True),
        )
        .values(is_default=False)
    )
    await db.commit()


async def resolve(
    db: AsyncSession, company_id: uuid.UUID, kind: str, template_id: TemplateRef = None
) -> tuple[uuid.UUID | None, Template]:
    """The subject and body a mail of ``kind`` renders from: an explicit row
    (``NotFound`` when it is not this workspace's), the Ganek default on
    ``"builtin"``, else the kind's default row, else the built-in."""
    if template_id == BUILTIN_ID:
        return None, email_render.BUILTIN[kind]
    if template_id is None:
        row = (
            await db.execute(
                select(EmailTemplate).where(
                    EmailTemplate.company_id == company_id,
                    EmailTemplate.kind == kind,
                    EmailTemplate.is_default.is_(True),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None, email_render.BUILTIN[kind]
        return row.id, Template(subject=row.subject, body=row.body)
    row = (
        await db.execute(
            select(EmailTemplate).where(
                EmailTemplate.company_id == company_id,
                EmailTemplate.id == template_id,
                EmailTemplate.kind == kind,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound
    return row.id, Template(subject=row.subject, body=row.body)


async def newest_published_job_title(db: AsyncSession, company: Company) -> str:
    title = (
        await db.execute(
            select(Job.title)
            .where(Job.company_id == company.id, Job.status == JobStatus.PUBLISHED)
            .order_by(Job.published_at.desc().nulls_last(), Job.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return title or SAMPLE_JOB_TITLE


def sample_context(company: Company, job_title: str, kind: str) -> dict[str, Any]:
    """The settings editor's preview context: a fictional candidate, the
    workspace's own values, links masked like the candidate preview."""
    now = datetime.now(UTC)
    context: dict[str, Any] = {
        "candidate_name": SAMPLE_CANDIDATE,
        "job_title": job_title,
        "company_name": company.name,
        "controller_name": company_service.controller_name(company),
        "privacy_url": urls.privacy_notice_url(company),
    }
    brand = (company.theme or {}).get("primary_color")
    if kind == "quiz_invite":
        context.update(
            brand_primary=brand,
            quiz_url=urls.quiz_url(company, PREVIEW_LINK_PLACEHOLDER),
            question_count=8,
            seconds_per_question=25,
            expires_at=now + timedelta(days=7),
        )
    elif kind == "quiz_reminder":
        context.update(
            brand_primary=brand,
            quiz_url=urls.quiz_url(company, PREVIEW_LINK_PLACEHOLDER),
            expires_at=now + timedelta(days=3),
            days_left=3,
        )
    elif kind == "stage_advance":
        context.update(
            brand_primary=brand,
            status_url=urls.status_url(company, PREVIEW_LINK_PLACEHOLDER),
        )
    else:
        context.update(careers_url=urls.careers_url(company), completed_assessment=True)
    return context
