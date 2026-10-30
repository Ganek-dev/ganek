"""Workspace email templates (card "Candidate emails", PR 3): admin CRUD
under /company/email-templates, one default per kind, the cap, tenancy and
the sample preview for unsaved text."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)

BASE = "/api/v1/company/email-templates"
KINDS = ["quiz_invite", "quiz_reminder", "stage_advance", "rejection"]
LABELS = ["Assessment invite", "Assessment reminder", "Interview", "Rejection"]


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _register_admin(client: AsyncClient) -> dict[str, str]:
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
        "password": "a-long-secure-password",
    }
    resp = await client.post(
        "/api/v1/auth/register", json={"company_name": f"Mail Co {uuid4().hex[:6]}", **creds}
    )
    assert resp.status_code == 201, resp.text
    return creds


async def _member_login(client: AsyncClient) -> None:
    """Creates a member in the current (admin) session and logs in as them."""
    member = {"email": f"member-{uuid4().hex[:8]}@ganek-ci.dev", "password": "member-password-1234"}
    resp = await client.post("/api/v1/users", json={**member, "role": "member"})
    assert resp.status_code == 201, resp.text
    await client.post("/api/v1/auth/logout")
    assert (await client.post("/api/v1/auth/login", json=member)).status_code == 200


def _rejection(name: str = "Warm no", **overrides: str) -> dict[str, str]:
    return {
        "kind": "rejection",
        "name": name,
        "subject": "About {{job_title}}",
        "body": "Thanks {{candidate_first_name}}\n\nNot this time.",
        **overrides,
    }


async def _create(client: AsyncClient, **overrides: str) -> dict[str, object]:
    resp = await client.post(BASE, json=_rejection(**overrides))
    assert resp.status_code == 201, resp.text
    body: dict[str, object] = resp.json()
    return body


async def _kind(client: AsyncClient, kind: str) -> dict[str, object]:
    resp = await client.get(BASE)
    assert resp.status_code == 200, resp.text
    entry: dict[str, object] = next(k for k in resp.json()["kinds"] if k["kind"] == kind)
    return entry


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_list_shows_four_kinds_with_builtin_and_placeholders(client: AsyncClient) -> None:
    await _register_admin(client)
    resp = await client.get(BASE)
    assert resp.status_code == 200, resp.text
    kinds = resp.json()["kinds"]
    assert [k["kind"] for k in kinds] == KINDS
    assert [k["label"] for k in kinds] == LABELS
    rejection = kinds[3]
    assert rejection["placeholders"] == [
        "candidate_name",
        "candidate_first_name",
        "job_title",
        "company_name",
        "assessment_thanks",
    ]
    assert rejection["builtin"]["subject"] == "Your application to {{company_name}}"
    assert rejection["builtin"]["body"].startswith("Thank you, {{candidate_name}}")
    assert all(k["templates"] == [] for k in kinds)


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_crud_lifecycle(client: AsyncClient) -> None:
    await _register_admin(client)
    created = await _create(client, name=" Warm no ")
    assert created["name"] == "Warm no"
    assert created["kind"] == "rejection"
    assert created["is_default"] is False
    assert created["subject"] == "About {{job_title}}"

    resp = await client.patch(
        f"{BASE}/{created['id']}", json={"name": "Warmer no", "subject": "Re {{job_title}}"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Warmer no"
    assert resp.json()["subject"] == "Re {{job_title}}"
    assert resp.json()["body"] == created["body"]

    listed = (await _kind(client, "rejection"))["templates"]
    assert [t["name"] for t in listed] == ["Warmer no"]  # type: ignore[index]

    assert (await client.delete(f"{BASE}/{created['id']}")).status_code == 204
    assert (await _kind(client, "rejection"))["templates"] == []
    assert (await client.delete(f"{BASE}/{created['id']}")).status_code == 404


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_unknown_placeholder_is_422_naming_it(client: AsyncClient) -> None:
    await _register_admin(client)
    resp = await client.post(BASE, json=_rejection(body="Pay {{salary}} and take {{quiz_url}}"))
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == "Unknown placeholders: quiz_url, salary"
    resp = await client.post(BASE, json=_rejection(subject="{{days_left}} left"))
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == "Unknown placeholder: days_left"
    assert (await _kind(client, "rejection"))["templates"] == []


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_blank_fields_are_422_and_a_single_paragraph_is_fine(client: AsyncClient) -> None:
    await _register_admin(client)
    assert (await client.post(BASE, json=_rejection(body="   "))).status_code == 422
    assert (await client.post(BASE, json=_rejection(name=""))).status_code == 422
    assert (await client.post(BASE, json=_rejection(subject=" "))).status_code == 422
    assert (await client.post(BASE, json={**_rejection(), "kind": "newsletter"})).status_code == 422
    resp = await client.post(BASE, json=_rejection(subject="{{company_name}}", body="Thanks"))
    assert resp.status_code == 201, resp.text


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_cap_is_twenty_per_kind(client: AsyncClient) -> None:
    await _register_admin(client)
    for i in range(20):
        await _create(client, name=f"Advance {i}", kind="stage_advance")
    resp = await client.post(BASE, json=_rejection(name="Advance 20", kind="stage_advance"))
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == "Up to 20 templates per kind"
    assert (await client.post(BASE, json=_rejection())).status_code == 201


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_set_default_switches_and_delete_falls_back_to_builtin(client: AsyncClient) -> None:
    await _register_admin(client)
    a = await _create(client, name="A")
    b = await _create(client, name="B")
    resp = await client.post(f"{BASE}/{a['id']}/default")
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_default"] is True
    resp = await client.post(f"{BASE}/{b['id']}/default")
    assert resp.status_code == 200, resp.text
    flags = {t["name"]: t["is_default"] for t in (await _kind(client, "rejection"))["templates"]}  # type: ignore[union-attr]
    assert flags == {"A": False, "B": True}
    assert (await client.delete(f"{BASE}/{b['id']}")).status_code == 204
    flags = {t["name"]: t["is_default"] for t in (await _kind(client, "rejection"))["templates"]}  # type: ignore[union-attr]
    assert flags == {"A": False}


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_member_reads_the_list_and_cannot_write(client: AsyncClient) -> None:
    await _register_admin(client)
    created = await _create(client)
    await _member_login(client)
    assert (await client.get(BASE)).status_code == 200
    assert (await client.post(BASE, json=_rejection(name="Mine"))).status_code == 403
    assert (await client.patch(f"{BASE}/{created['id']}", json={"name": "x"})).status_code == 403
    assert (await client.delete(f"{BASE}/{created['id']}")).status_code == 403
    assert (await client.post(f"{BASE}/{created['id']}/default")).status_code == 403
    preview = {"kind": "rejection", "subject": "s", "body": "b"}
    assert (await client.post(f"{BASE}/preview", json=preview)).status_code == 403


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_templates_are_tenant_scoped(client: AsyncClient) -> None:
    await _register_admin(client)
    created = await _create(client)
    await client.post("/api/v1/auth/logout")
    await _register_admin(client)
    assert (await _kind(client, "rejection"))["templates"] == []
    assert (await client.patch(f"{BASE}/{created['id']}", json={"name": "x"})).status_code == 404
    assert (await client.delete(f"{BASE}/{created['id']}")).status_code == 404
    assert (await client.post(f"{BASE}/{created['id']}/default")).status_code == 404


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_sample_preview_renders_unsaved_text(client: AsyncClient) -> None:
    await _register_admin(client)
    resp = await client.post(
        f"{BASE}/preview",
        json={
            "kind": "quiz_invite",
            "subject": "Hi {{candidate_first_name}}",
            "body": (
                "{{question_count}} questions, {{time_per_question}} each\n\n"
                "Valid until {{valid_until}}"
            ),
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "quiz_invite"
    assert body["subject"] == "Hi Alex"
    assert body["text"].startswith("8 questions, 25s each")
    assert "Start the assessment" in body["html"]
    assert "personal-link" in body["html"]
    resp = await client.post(
        f"{BASE}/preview", json={"kind": "rejection", "subject": "x", "body": "{{quiz_url}}"}
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == "Unknown placeholder: quiz_url"
