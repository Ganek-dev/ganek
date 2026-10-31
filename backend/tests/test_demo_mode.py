"""Demo mode (GANEK_DEMO_MODE): apply keeps working but nothing a visitor
types or uploads is stored, nothing is mailed, and the endpoints that would
lock other visitors out of the shared account answer 403."""

import re
from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.config import settings
from app.models import Candidate, EmailOutbox
from app.schemas.public import ApplicationSubmit
from app.services import demo_mode, storage
from app.services.screening import validate_questions
from tests.db import database_reachable, s3_reachable

PASSWORD = "a-long-secure-password"
db_required = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)


def _real_submission(**overrides: object) -> ApplicationSubmit:
    return ApplicationSubmit.model_validate(
        {
            "name": "Real Person",
            "email": "real.person@gmail.com",
            "message": "My phone number is +49 170 0000000",
            "github": "https://github.com/real-person",
            "linkedin": "https://www.linkedin.com/in/real-person",
            "portfolio": "https://real-person.dev",
            "cv_object_key": "cvs/x/real.pdf",
            "cv_filename": "real.pdf",
            "altcha": "solved",
            **overrides,
        }
    )


# --- pure -------------------------------------------------------------------


def test_pseudonymize_keeps_the_source() -> None:
    # where the candidate came from is not visitor-typed text; it stays
    out = demo_mode.pseudonymize(
        ApplicationSubmit(name="Real Person", email="real@example.org", source="linkedin"),
        cv_object_key="k",
    )
    assert out.source == "linkedin"


def test_pseudonymize_replaces_every_personal_value() -> None:
    out = demo_mode.pseudonymize(_real_submission(), cv_object_key="cvs/c/demo-sample.pdf")
    assert out.name.startswith("Demo Candidate ")
    assert out.email.endswith("@example.com") and "real" not in out.email
    assert out.message is None
    assert out.links() == demo_mode.DEMO_LINKS
    assert out.cv_object_key == "cvs/c/demo-sample.pdf"
    assert out.cv_filename == demo_mode.SAMPLE_CV_FILENAME
    assert out.altcha == "solved"  # already verified, carries no PII
    dumped = out.model_dump_json()
    for leaked in ("Real Person", "gmail", "real-person", "+49"):
        assert leaked not in dumped
    # two applies never collide on the candidate email
    again = demo_mode.pseudonymize(_real_submission(), cv_object_key="k")
    assert again.email != out.email


def test_sample_cv_is_a_well_formed_pdf() -> None:
    pdf = demo_mode.SAMPLE_CV_PDF
    assert pdf.startswith(b"%PDF-1.4\n") and pdf.endswith(b"%%EOF\n")
    assert b"ACME Ganek - sample CV" in pdf and b"/Helvetica" in pdf
    match = re.search(rb"startxref\n(\d+)\n", pdf)
    assert match is not None
    assert pdf[int(match.group(1)) :].startswith(b"xref\n0 6\n")
    assert len(pdf) < 4096


def test_cv_fields_are_optional_in_the_schema_only() -> None:
    payload = ApplicationSubmit.model_validate({"name": "A", "email": "a@example.com"})
    assert payload.cv_object_key is None and payload.cv_filename is None
    with pytest.raises(ValueError):
        ApplicationSubmit.model_validate(
            {"name": "A", "email": "a@example.com", "cv_object_key": "k", "cv_filename": "x.txt"}
        )


async def test_lock_and_upload_guard_only_bite_in_demo_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "demo_mode", False)
    await demo_mode._locked()
    demo_mode.forbid_upload()
    monkeypatch.setattr(settings, "demo_mode", True)
    with pytest.raises(HTTPException) as locked:
        await demo_mode._locked()
    assert locked.value.status_code == 403 and locked.value.detail == demo_mode.LOCKED_DETAIL
    with pytest.raises(HTTPException) as upload:
        demo_mode.forbid_upload()
    assert upload.value.status_code == 403 and upload.value.detail == demo_mode.UPLOAD_DETAIL


async def test_providers_reports_the_flag_and_the_demo_login(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    normal = (await client.get("/api/v1/auth/providers")).json()
    assert normal["demo"] is False and "demo_login" not in normal
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "demo_reset_slug", None)
    monkeypatch.setattr(settings, "demo_password", "published-demo-pw")
    demo = (await client.get("/api/v1/auth/providers")).json()
    assert demo["demo"] is True
    assert demo["demo_login"] == {"email": "erika@acme.example", "password": "published-demo-pw"}


# --- API --------------------------------------------------------------------


@pytest.fixture
def _multi_no_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ratelimit, "_redis_broken", True)
    ratelimit._memory.clear()
    monkeypatch.setattr(settings, "mode", "multi")
    monkeypatch.setattr(settings, "quota_emails_per_day", 0)
    monkeypatch.setattr(settings, "quota_applications_per_hour", 0)
    monkeypatch.setattr(settings, "quota_active_jobs", 0)


async def _company_with_job(client: AsyncClient) -> tuple[str, str, str]:
    """Registers an admin (session stays logged in) with one published job.
    Returns (company_slug, job_slug, company_id)."""
    name = f"Demo Co {uuid4().hex[:6]}"
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": name,
            "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
            "password": PASSWORD,
        },
    )
    assert resp.status_code == 201, resp.text
    company_id = (await client.get("/api/v1/auth/me")).json()["company_id"]
    job = (await client.post("/api/v1/jobs", json={"title": "Backend Engineer"})).json()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    return name.lower().replace(" ", "-"), job["slug"], company_id


@db_required
@pytest.mark.usefixtures("migrated_db", "bucket", "_multi_no_limits")
async def test_demo_apply_stores_nothing_the_visitor_typed(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    slug, job_slug, company_id = await _company_with_job(client)
    monkeypatch.setattr(settings, "demo_mode", True)
    base = f"/api/v1/public/companies/{slug}/jobs/{job_slug}"

    upload = await client.post(f"{base}/apply/upload-url")
    assert upload.status_code == 403 and upload.json()["detail"] == demo_mode.UPLOAD_DETAIL

    real = _real_submission().model_dump(mode="json", exclude={"cv_object_key", "cv_filename"})
    real["altcha"] = None
    resp = await client.post(f"{base}/apply", json=real)
    assert resp.status_code == 201, resp.text
    assert resp.json()["status_token"]

    page = (await client.get("/api/v1/applications")).json()
    assert len(page["items"]) == 1
    app_out = page["items"][0]
    assert app_out["candidate"]["name"].startswith("Demo Candidate ")
    assert app_out["candidate"]["email"].endswith("@example.com")
    assert app_out["candidate"]["links"] == demo_mode.DEMO_LINKS
    assert app_out["message"] is None
    assert app_out["cv_filename"] == demo_mode.SAMPLE_CV_FILENAME
    assert app_out["cv_size"] == len(demo_mode.SAMPLE_CV_PDF)
    listing = (await client.get("/api/v1/applications")).text
    for leaked in ("Real Person", "gmail", "real-person", "+49"):
        assert leaked not in listing

    real_rows = await db_session.execute(
        select(func.count()).select_from(Candidate).where(Candidate.email == real["email"])
    )
    assert real_rows.scalar_one() == 0
    queued = await db_session.execute(
        select(func.count()).select_from(EmailOutbox).where(EmailOutbox.company_id == company_id)
    )
    assert queued.scalar_one() == 0

    key = f"cvs/{company_id}/demo-sample.pdf"
    stat = await storage.stat_object(key)
    assert stat is not None and stat.size == len(demo_mode.SAMPLE_CV_PDF)
    # a second applicant reuses the one sample object
    assert (await client.post(f"{base}/apply", json=real)).status_code == 201
    page = (await client.get("/api/v1/applications")).json()
    assert len(page["items"]) == 2 and len({i["candidate"]["email"] for i in page["items"]}) == 2


@db_required
@pytest.mark.usefixtures("migrated_db", "bucket", "_multi_no_limits")
async def test_apply_without_a_cv_is_422_outside_demo_mode(client: AsyncClient) -> None:
    slug, job_slug, _ = await _company_with_job(client)
    resp = await client.post(
        f"/api/v1/public/companies/{slug}/jobs/{job_slug}/apply",
        json={"name": "No CV", "email": f"nocv-{uuid4().hex[:6]}@ganek-ci.dev"},
    )
    assert resp.status_code == 422 and resp.json()["detail"] == "CV is required"


@db_required
@pytest.mark.usefixtures("migrated_db", "bucket", "_multi_no_limits")
async def test_demo_locks_the_shared_account_and_leaves_the_rest_open(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _company_with_job(client)
    me = (await client.get("/api/v1/auth/me")).json()
    monkeypatch.setattr(settings, "demo_mode", True)

    locked = [
        client.post("/api/v1/auth/change-password", json={}),
        client.post("/api/v1/auth/forgot-password", json={}),
        client.post("/api/v1/auth/reset-password", json={}),
        client.post("/api/v1/auth/mfa/enrol"),
        client.post("/api/v1/auth/mfa/confirm", json={}),
        client.post("/api/v1/auth/mfa/disable", json={}),
        client.post("/api/v1/auth/sign-out-everywhere"),
        client.post("/api/v1/users", json={}),
        client.post("/api/v1/users/invites", json={}),
        client.post(f"/api/v1/users/invites/{uuid4()}/resend"),
        client.patch(f"/api/v1/users/{me['id']}", json={}),
        client.post(f"/api/v1/users/{me['id']}/anonymize"),
        client.get("/api/v1/auth/google/start"),
    ]
    for pending in locked:
        resp = await pending
        assert resp.status_code == 403, (resp.request.url, resp.status_code, resp.text)
        assert resp.json()["detail"] == demo_mode.LOCKED_DETAIL

    # still open: the integration surface and the session itself
    key = await client.post("/api/v1/api-keys", json={"name": "demo key", "scope": "read"})
    assert key.status_code == 201, key.text
    assert (await client.get("/api/v1/auth/me")).status_code == 200
    assert (
        await client.post("/api/v1/jobs", json={"title": "Open on the demo"})
    ).status_code == 201


def test_pseudonymize_keeps_choice_answers_and_replaces_text_answers() -> None:
    questions = validate_questions(
        [
            {"id": "sq_0000aa01", "type": "yes_no", "prompt": "Permit?", "preferred": "yes"},
            {"id": "sq_0000aa03", "type": "short_text", "prompt": "Notice period?"},
            {"id": "sq_0000aa04", "type": "acknowledgment", "prompt": "I confirm"},
        ]
    )
    out = demo_mode.pseudonymize(
        _real_submission(
            screening_answers=[
                {"question_id": "sq_0000aa01", "answer": "yes"},
                {"question_id": "sq_0000aa03", "answer": "My phone number is +49 170 0000000"},
                {"question_id": "sq_0000aa04", "answer": True},
            ]
        ),
        cv_object_key="k",
        questions=questions,
    )
    answers = {a.question_id: a.answer for a in out.screening_answers}
    assert answers["sq_0000aa01"] == "yes"
    assert answers["sq_0000aa03"] == demo_mode.TEXT_ANSWER_PLACEHOLDER
    assert answers["sq_0000aa04"] is True
    assert "+49" not in out.model_dump_json()
