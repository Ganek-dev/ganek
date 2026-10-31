"""Demo mode (GANEK_DEMO_MODE): a public demo workspace that never stores a
real person's data and keeps working for the next visitor.

Public apply stays on so visitors can run the whole candidate flow, but
what they type is replaced before anything is written: name, email and
links become fictional values, the message is dropped and no CV is ever
uploaded (one sample PDF is attached instead). Nothing is mailed. The few
endpoints that would lock other visitors out of the shared account, or
pull a real person's data in, answer 403. Everything else stays open; the
nightly reset (worker.reset_demo) is the backstop for vandalism.
"""

import secrets

from fastapi import Depends, HTTPException, status
from fastapi import params as fastapi_params

from app.core.config import settings
from app.models import Company
from app.schemas.public import ApplicationSubmit
from app.services import demo_seed, storage
from app.services.screening import ScreeningAnswerIn, ScreeningQuestion

# every link a demo applicant can carry points at something Ganek owns
DEMO_LINKS = {
    "github": "https://github.com/Ganek-dev",
    "linkedin": "https://www.linkedin.com/company/ganek-io",
    "portfolio": "https://ganek.io/",  # as HttpUrl normalises it
}
SAMPLE_CV_FILENAME = "acme-ganek-sample-cv.pdf"
LOCKED_DETAIL = "Disabled on the demo workspace"
UPLOAD_DETAIL = "CV upload is off on the demo; a sample CV is attached to every application"


def enabled() -> bool:
    return settings.demo_mode


def demo_login() -> dict[str, str]:
    """The shared admin login the login page offers with one click. Public by
    design on a demo (visitors need it); only ever exposed while demo mode is
    on, see /auth/providers."""
    slug = settings.demo_reset_slug or demo_seed.DEFAULT_SLUG
    return {
        "email": f"erika@{slug}.example",
        "password": settings.demo_password or demo_seed.DEFAULT_PASSWORD,
    }


def _pdf(lines: list[str]) -> bytes:
    """A one-page Helvetica PDF with a valid xref, so viewers open it and the
    CV check (size, content type) accepts it."""
    text = "\n".join(
        f"BT /F1 {size} Tf 56 {y} Td ({line}) Tj ET"
        for line, size, y in (
            (lines[0], 20, 770),
            *((ln, 11, 740 - 18 * i) for i, ln in enumerate(lines[1:])),
        )
    )
    stream = text.encode("latin-1")
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Resources<</Font<</F1 4 0 R>>>>"
        b"/Contents 5 0 R>>",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
        b"<</Length " + str(len(stream)).encode() + b">>stream\n" + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer<</Size {len(objects) + 1}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


SAMPLE_CV_PDF = _pdf(
    [
        "ACME Ganek - sample CV",
        "This workspace is a demo. Nothing a visitor types or uploads is kept.",
        "Every application gets this document instead of the uploaded file;",
        "the applicant's name, email and links are fictional as well.",
        "",
        "Demo Candidate",
        "Software engineer, 5 years, Python and TypeScript",
        "Berlin, works remotely",
        "",
        "The workspace resets every night.",
    ]
)


def sample_cv_key(company: Company) -> str:
    # under the company prefix so the ordinary CV ownership check passes
    return f"cvs/{company.id}/demo-sample.pdf"


async def ensure_sample_cv(company: Company) -> str:
    key = sample_cv_key(company)
    if await storage.stat_object(key) is None:
        await storage.put_object(key, SAMPLE_CV_PDF, storage.CV_CONTENT_TYPE)
    return key


TEXT_ANSWER_PLACEHOLDER = "(text answers are not kept on the demo)"


def pseudonymize(
    payload: ApplicationSubmit,
    *,
    cv_object_key: str,
    questions: list[ScreeningQuestion] | None = None,
) -> ApplicationSubmit:
    """The same submission with every personal value replaced. Only the
    captcha payload survives: it was already verified and carries no PII.
    Screening answers to choice and acknowledgment questions are kept (they
    are picks, not typed text); short-text answers become a placeholder."""
    tag = secrets.token_hex(3)
    text_ids = {q.id for q in questions or [] if q.type == "short_text"}
    return ApplicationSubmit(
        name=f"Demo Candidate {tag}",
        email=f"demo-{tag}@example.com",
        message=None,
        github=DEMO_LINKS["github"],
        linkedin=DEMO_LINKS["linkedin"],
        portfolio=DEMO_LINKS["portfolio"],
        cv_object_key=cv_object_key,
        cv_filename=SAMPLE_CV_FILENAME,
        source=payload.source,
        altcha=payload.altcha,
        screening_answers=[
            ScreeningAnswerIn(
                question_id=answer.question_id,
                answer=(
                    TEXT_ANSWER_PLACEHOLDER
                    if answer.question_id in text_ids and answer.answer not in (None, "")
                    else answer.answer
                ),
            )
            for answer in payload.screening_answers
        ],
    )


async def sanitize(
    company: Company,
    payload: ApplicationSubmit,
    *,
    questions: list[ScreeningQuestion] | None = None,
) -> ApplicationSubmit:
    """What the public apply route stores instead of the visitor's input."""
    return pseudonymize(payload, cv_object_key=await ensure_sample_cv(company), questions=questions)


def forbid_upload() -> None:
    if settings.demo_mode:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=UPLOAD_DETAIL)


async def _locked() -> None:
    if settings.demo_mode:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=LOCKED_DETAIL)


# `dependencies=[demo_mode.locked]` on an endpoint that must not run on the demo
locked: fastapi_params.Depends = Depends(_locked)
