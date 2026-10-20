"""User display names (board card D14): own profile edit, the shared
fallback label, the team list, and anonymize clearing it."""

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import User
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)

PASSWORD = "a-long-secure-password"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _register(client: AsyncClient, local: str) -> dict[str, str]:
    creds = {"email": f"{local}-{uuid4().hex[:6]}@ganek-ci.dev", "password": PASSWORD}
    resp = await client.post(
        "/api/v1/auth/register", json={"company_name": f"Names Co {uuid4().hex[:6]}", **creds}
    )
    assert resp.status_code == 201, resp.text
    return creds


def test_display_label_falls_back_to_a_readable_local_part() -> None:
    assert User(email="jane.doe@acme.example").display_label == "Jane Doe"
    assert User(email="jane_doe-x@acme.example").display_label == "Jane Doe X"
    assert User(email="jd@acme.example", display_name="Jane D.").display_label == "Jane D."
    assert User(email="jd@acme.example", display_name="").display_label == "Jd"


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_profile_sets_and_clears_the_name_and_me_reports_it(client: AsyncClient) -> None:
    creds = await _register(client, "erika.mustermann")
    # the helper suffixes the local part (erika.mustermann-<hex>), so derive
    # the expected label the way the model does
    derived = creds["email"].split("@")[0].replace(".", " ").replace("-", " ").title()
    assert derived.startswith("Erika Mustermann ")
    me = (await client.get("/api/v1/auth/me")).json()
    assert me["display_name"] is None
    assert me["display_label"] == derived

    resp = await client.patch("/api/v1/users/me", json={"display_name": "  Erika M.  "})
    assert resp.status_code == 200, resp.text
    assert resp.json()["display_name"] == "Erika M."
    assert resp.json()["display_label"] == "Erika M."
    assert (await client.get("/api/v1/auth/me")).json()["display_label"] == "Erika M."

    team = (await client.get("/api/v1/users")).json()
    assert [u["display_label"] for u in team] == ["Erika M."]

    resp = await client.patch("/api/v1/users/me", json={"display_name": ""})
    assert resp.status_code == 200
    assert resp.json()["display_name"] is None
    assert resp.json()["display_label"] == derived

    too_long = await client.patch("/api/v1/users/me", json={"display_name": "x" * 101})
    assert too_long.status_code == 422


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_anonymize_clears_the_display_name(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _register(client, "admin")
    member = {"email": f"member-{uuid4().hex[:6]}@ganek-ci.dev", "password": PASSWORD}
    created = await client.post("/api/v1/users", json={**member, "role": "member"})
    assert created.status_code == 201, created.text
    member_id = created.json()["id"]

    # the member names themselves
    await client.post("/api/v1/auth/logout")
    assert (await client.post("/api/v1/auth/login", json=member)).status_code == 200
    assert (
        await client.patch("/api/v1/users/me", json={"display_name": "Max Mustermann"})
    ).status_code == 200
    await client.post("/api/v1/auth/logout")

    # the admin removes them: the name goes with the email
    assert (await client.post("/api/v1/auth/login", json=admin)).status_code == 200
    gone = await client.post(f"/api/v1/users/{member_id}/anonymize")
    assert gone.status_code == 204, gone.text
    row = (await db_session.execute(select(User).where(User.id == member_id))).scalar_one()
    assert row.display_name is None
    assert row.email.startswith("deleted-")
