import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import AdminUser, CurrentCompany, DbSession
from app.models import EmailTemplate
from app.schemas.applications import EmailPreviewOut
from app.schemas.email_templates import (
    BuiltinTemplateOut,
    EmailKindIn,
    EmailKindOut,
    EmailTemplateCreate,
    EmailTemplateOut,
    EmailTemplatePreviewIn,
    EmailTemplatesOut,
    EmailTemplateUpdate,
)
from app.services import email_render
from app.services import email_templates as templates_service

# template management is admin territory (like Privacy and Team); the list
# is readable by any member because the stage dialog picker needs it
router = APIRouter(prefix="/company/email-templates", tags=["email-templates"])

NOT_FOUND = "Template not found"


def _invalid(exc: templates_service.InvalidTemplate) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.detail)


@router.get("", response_model=EmailTemplatesOut)
async def list_email_templates(db: DbSession, company: CurrentCompany) -> EmailTemplatesOut:
    rows = await templates_service.list_for(db, company)
    return EmailTemplatesOut(
        kinds=[
            EmailKindOut(
                kind=kind,
                label=templates_service.KIND_LABELS[kind],
                placeholders=list(email_render.PLACEHOLDERS[kind]),
                builtin=BuiltinTemplateOut(
                    subject=email_render.BUILTIN[kind].subject,
                    body=email_render.BUILTIN[kind].body,
                ),
                templates=[row for row in rows if row.kind == kind],
            )
            for kind in email_render.KINDS
        ]
    )


@router.post("", response_model=EmailTemplateOut, status_code=status.HTTP_201_CREATED)
async def create_email_template(
    payload: EmailTemplateCreate, db: DbSession, company: CurrentCompany, admin: AdminUser
) -> EmailTemplate:
    try:
        return await templates_service.create(
            db,
            company,
            kind=payload.kind,
            name=payload.name,
            subject=payload.subject,
            body=payload.body,
            actor_user_id=admin.id,
        )
    except templates_service.InvalidTemplate as exc:
        raise _invalid(exc) from None
    except templates_service.CapReached:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Up to {templates_service.CAP_PER_KIND} templates per kind",
        ) from None


@router.post("/preview", response_model=EmailPreviewOut)
async def preview_email_template(
    payload: EmailTemplatePreviewIn, db: DbSession, company: CurrentCompany, _admin: AdminUser
) -> EmailPreviewOut:
    """The editor's live preview: unsaved text rendered with a sample
    candidate and the workspace's own values. Nothing is stored."""
    # literal path, declared before /{template_id} routes
    try:
        _, subject, body = templates_service.clean(
            payload.kind, None, payload.subject, payload.body
        )
    except templates_service.InvalidTemplate as exc:
        raise _invalid(exc) from None
    job_title = await templates_service.newest_published_job_title(db, company)
    context = templates_service.sample_context(company, job_title, payload.kind)
    rendered = email_render.render(payload.kind, email_render.Template(subject, body), context)
    return EmailPreviewOut(
        kind=payload.kind,
        subject=rendered.subject,
        text=rendered.text,
        html=rendered.html,
        body=rendered.body,
    )


@router.post("/builtin/default", status_code=status.HTTP_204_NO_CONTENT)
async def reset_default_email_template(
    payload: EmailKindIn, db: DbSession, company: CurrentCompany, _admin: AdminUser
) -> None:
    """Make the Ganek default the kind's default again (no row keeps the
    flag). Literal path, declared before /{template_id} routes."""
    try:
        await templates_service.clear_default(db, company, payload.kind)
    except templates_service.InvalidTemplate as exc:
        raise _invalid(exc) from None


@router.patch("/{template_id}", response_model=EmailTemplateOut)
async def update_email_template(
    template_id: uuid.UUID,
    payload: EmailTemplateUpdate,
    db: DbSession,
    company: CurrentCompany,
    _admin: AdminUser,
) -> EmailTemplate:
    try:
        return await templates_service.update_template(
            db,
            company,
            template_id,
            name=payload.name,
            subject=payload.subject,
            body=payload.body,
        )
    except templates_service.NotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND) from None
    except templates_service.InvalidTemplate as exc:
        raise _invalid(exc) from None


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_email_template(
    template_id: uuid.UUID, db: DbSession, company: CurrentCompany, _admin: AdminUser
) -> None:
    try:
        await templates_service.delete(db, company, template_id)
    except templates_service.NotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND) from None


@router.post("/{template_id}/default", response_model=EmailTemplateOut)
async def set_default_email_template(
    template_id: uuid.UUID, db: DbSession, company: CurrentCompany, _admin: AdminUser
) -> EmailTemplate:
    try:
        return await templates_service.set_default(db, company, template_id)
    except templates_service.NotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND) from None
