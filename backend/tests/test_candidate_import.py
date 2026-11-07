"""CSV import of candidates into a job: rows mapped in the browser become
applications without a CV, each new person gets the job's invite with the
GDPR art. 14 data-origin paragraph, duplicates by email per company are
skipped and counted, and one activity entry records the import."""

from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.services import email as email_service
from app.services import email_render
from tests.db import database_reachable, s3_reachable

pytestmark_db = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)

ORIGIN = "our Personio account"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(email_service, "send_email", lambda **kw: captured.append(kw))
    return captured


# --- DB-free ---------------------------------------------------------------


def _context(**extra: object) -> dict[str, object]:
    return {
        "candidate_name": "Jane Doe",
        "job_title": "Backend Engineer",
        "company_name": "Acme <Labs>",
        "privacy_url": "https://acme.example/privacy",
        "controller_name": "Acme Labs GmbH",
        **extra,
    }


def test_data_origin_paragraph_in_text_and_html() -> None:
    rendered = email_render.render(
        "application_received",
        email_render.BUILTIN["application_received"],
        _context(data_origin="our <ATS> export"),
    )
    assert "received your name and email address from our <ATS> export" in rendered.text
    assert "not from you directly" in rendered.text
    assert "consider you for Backend Engineer" in rendered.text
    assert "our &lt;ATS&gt; export" in rendered.html
    assert "<ATS>" not in rendered.html
    # the template part (what "Edit this email" prefills) stays the template
    assert "not from you directly" not in rendered.body


def test_no_data_origin_paragraph_without_an_origin() -> None:
    rendered = email_render.render(
        "application_received", email_render.BUILTIN["application_received"], _context()
    )
    assert "not from you directly" not in rendered.text
    assert "not from you directly" not in rendered.html


# --- DB ---------------------------------------------------------------------


async def _job(client: AsyncClient, *, with_quiz: bool, publish: bool = True) -> dict[str, Any]:
    name = f"Import Co {uuid4().hex[:6]}"
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": name,
            "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
            "password": "a-long-secure-password",
        },
    )
    assert resp.status_code == 201, resp.text
    payload: dict[str, object] = {"title": "Backend Engineer"}
    if with_quiz:
        payload["tags"] = ["python"]
        payload["quiz_config"] = {"enabled": True, "question_count": 3}
    job: dict[str, Any] = (await client.post("/api/v1/jobs", json=payload)).json()
    if publish:
        assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    return job


def _rows(*pairs: tuple[str, str], source: str | None = None) -> list[dict[str, object]]:
    return [{"name": name, "email": email, "source": source} for name, email in pairs]


@pytestmark_db
@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_import_creates_applications_and_sends_invites(
    client: AsyncClient, sent: list[dict[str, Any]]
) -> None:
    job = await _job(client, with_quiz=True)
    tag = uuid4().hex[:6]
    a, b = f"ada-{tag}@ganek-ci.dev", f"bob-{tag}@ganek-ci.dev"
    rows = _rows(
        ("Ada Lovelace", a),
        ("Bob Builder", b),
        ("Ada Again", a.upper()),  # repeat inside the file, case-insensitive
        ("", f"noname-{tag}@ganek-ci.dev"),  # invalid: no name
        ("Bad Email", "not-an-email"),  # invalid
    )
    url = f"/api/v1/jobs/{job['id']}/import"

    preview = await client.post(url, json={"rows": rows, "origin": ORIGIN, "dry_run": True})
    assert preview.status_code == 200, preview.text
    assert preview.json() == {
        "imported": 2,
        "duplicates": 1,
        "invalid": 2,
        "duplicate_rows": [3],
        "invalid_rows": [4, 5],
        "dry_run": True,
    }
    assert sent == []
    assert (await client.get("/api/v1/applications")).json()["items"] == []

    resp = await client.post(url, json={"rows": rows, "origin": ORIGIN})
    assert resp.status_code == 200, resp.text
    assert resp.json()["imported"] == 2 and resp.json()["duplicates"] == 1

    items = (await client.get("/api/v1/applications")).json()["items"]
    assert sorted(item["candidate"]["email"] for item in items) == sorted([a, b])
    assert all(item["cv_filename"] is None for item in items)
    assert {item["source"] for item in items} == {"link:import"}

    assert sorted(mail["to"] for mail in sent) == sorted([a, b])
    for mail in sent:
        assert "/quiz/" in mail["body"]  # the assessment invite
        assert f"from {ORIGIN}, not from you directly" in mail["body"]
        assert "not from you directly" in mail["html"]

    # importing the same file again: everyone is already a candidate
    sent.clear()
    again = await client.post(url, json={"rows": rows, "origin": ORIGIN})
    assert again.json()["imported"] == 0 and again.json()["duplicates"] == 3
    assert sent == []

    feed = (await client.get("/api/v1/activity")).json()
    imports = [row for row in feed if row["type"] == "applications.imported"]
    assert [row["payload"]["count"] for row in imports] == [0, 2]
    assert imports[1]["payload"]["duplicates"] == 1
    assert imports[1]["payload"]["invalid"] == 2
    assert imports[1]["payload"]["origin"] == ORIGIN
    assert imports[1]["actor_email"]
    # per-row received entries stay out of the dashboard feed
    assert not [row for row in feed if row["type"] == "application.received"]


@pytestmark_db
@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_import_round_trips_the_ganek_export(
    client: AsyncClient, sent: list[dict[str, Any]]
) -> None:
    """Rows taken from another workspace's export (candidate_name,
    candidate_email, source) import; a known source is kept, and a job
    without an assessment sends the confirmation with the origin."""
    source_job = await _job(client, with_quiz=False)
    tag = uuid4().hex[:6]
    first = await client.post(
        f"/api/v1/jobs/{source_job['id']}/import",
        json={
            "rows": _rows(("Grace Hopper", f"grace-{tag}@ganek-ci.dev"), source="linkedin"),
            "origin": "a spreadsheet",
        },
    )
    assert first.status_code == 200, first.text
    exported = (await client.get("/api/v1/applications/export", params={"format": "json"})).json()
    exported = exported if isinstance(exported, list) else exported["items"]
    assert exported[0]["source"] == "linkedin"
    await client.post("/api/v1/auth/logout")

    target_job = await _job(client, with_quiz=False)
    sent.clear()
    rows = [
        {"name": row["candidate_name"], "email": row["candidate_email"], "source": row["source"]}
        for row in exported
    ]
    resp = await client.post(
        f"/api/v1/jobs/{target_job['id']}/import",
        json={"rows": rows, "origin": "the Ganek export of our other workspace"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["imported"] == 1
    items = (await client.get("/api/v1/applications")).json()["items"]
    assert [item["candidate"]["name"] for item in items] == ["Grace Hopper"]
    assert items[0]["source"] == "linkedin"
    assert len(sent) == 1
    assert "Thanks for applying" in sent[0]["body"]  # the confirmation, no quiz
    assert "from the Ganek export of our other workspace" in sent[0]["body"]


@pytestmark_db
@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_import_refuses_unpublished_jobs_and_blank_origin(client: AsyncClient) -> None:
    job = await _job(client, with_quiz=False, publish=False)
    rows = _rows(("Ada", f"ada-{uuid4().hex[:6]}@ganek-ci.dev"))
    url = f"/api/v1/jobs/{job['id']}/import"
    resp = await client.post(url, json={"rows": rows, "origin": ORIGIN})
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Publish the job before importing candidates"
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    blank = await client.post(url, json={"rows": rows, "origin": "   "})
    assert blank.status_code == 422
    empty = await client.post(url, json={"rows": [], "origin": ORIGIN})
    assert empty.status_code == 422
    other = await client.post(
        f"/api/v1/jobs/{uuid4()}/import", json={"rows": rows, "origin": ORIGIN}
    )
    assert other.status_code == 404
