"""Company default screening questions (board card "Per-job screening
questions"): admins write the set through PATCH /company/settings, every
signed-in member reads it from GET /company/summary (members create jobs
and the new-job editor prefills from it), members cannot write it."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)

SCREENING = [
    {"type": "yes_no", "prompt": "Can you work in Germany?", "preferred": "yes", "required": True},
    {"type": "acknowledgment", "prompt": "I confirm the information is accurate"},
]


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _register_admin(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": f"Screening Co {uuid4().hex[:6]}",
            "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
            "password": "a-long-secure-password",
        },
    )
    assert resp.status_code == 201, resp.text


async def _switch_to_member(client: AsyncClient) -> None:
    email = f"member-{uuid4().hex[:8]}@ganek-ci.dev"
    password = "member-password-1234"
    resp = await client.post(
        "/api/v1/users", json={"email": email, "password": password, "role": "member"}
    )
    assert resp.status_code == 201, resp.text
    await client.post("/api/v1/auth/logout")
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_defaults_visible_to_members_writable_by_admins(client: AsyncClient) -> None:
    await _register_admin(client)
    resp = await client.patch("/api/v1/company/settings", json={"screening_questions": SCREENING})
    assert resp.status_code == 200, resp.text
    saved = resp.json()["screening_questions"]
    assert [q["type"] for q in saved] == ["yes_no", "acknowledgment"]
    assert saved[1]["required"] is True
    # the admin company view and the any-role summary both carry the set
    assert len((await client.get("/api/v1/company")).json()["screening_questions"]) == 2
    assert len((await client.get("/api/v1/company/summary")).json()["screening_questions"]) == 2
    # other settings keys are untouched by a screening-only PATCH
    assert "screening_questions" not in (await client.get("/api/v1/company")).json()["settings"]

    await _switch_to_member(client)
    summary = await client.get("/api/v1/company/summary")
    assert summary.status_code == 200
    assert len(summary.json()["screening_questions"]) == 2
    resp = await client.patch("/api/v1/company/settings", json={"screening_questions": []})
    assert resp.status_code == 403, resp.text


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_defaults_validation_and_untouched_when_absent(client: AsyncClient) -> None:
    await _register_admin(client)
    too_many = [{"type": "yes_no", "prompt": f"q{i}"} for i in range(21)]
    resp = await client.patch("/api/v1/company/settings", json={"screening_questions": too_many})
    assert resp.status_code == 422, resp.text
    await client.patch("/api/v1/company/settings", json={"screening_questions": SCREENING})
    resp = await client.patch("/api/v1/company/settings", json={"legal_name": "Screening GmbH"})
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["screening_questions"]) == 2
