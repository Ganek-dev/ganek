"""Branding settings API (screen 10): admin GET /company + PATCH /company/branding."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _register_admin(client: AsyncClient) -> str:
    name = f"Brand Co {uuid4().hex[:6]}"
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": name,
            "email": f"admin-{uuid4().hex[:8]}@vetd-ci.dev",
            "password": "a-long-secure-password",
        },
    )
    assert resp.status_code == 201, resp.text
    return name.lower().replace(" ", "-")


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_get_company_and_update_branding(client: AsyncClient) -> None:
    slug = await _register_admin(client)

    resp = await client.get("/api/v1/company")
    assert resp.status_code == 200, resp.text
    assert resp.json()["slug"] == slug
    assert resp.json()["theme"] == {}

    resp = await client.patch(
        "/api/v1/company/branding", json={"primary_color": "#7E14FF", "radius": "round"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["theme"] == {"primary_color": "#7E14FF", "radius": "round"}

    # partial patch touches only the sent key
    resp = await client.patch("/api/v1/company/branding", json={"radius": "sharp"})
    assert resp.json()["theme"] == {"primary_color": "#7E14FF", "radius": "sharp"}

    # explicit null resets a key to the default
    resp = await client.patch("/api/v1/company/branding", json={"primary_color": None})
    assert resp.json()["theme"] == {"radius": "sharp"}

    # the public careers page sees the saved theme
    public = await client.get(f"/api/v1/public/companies/{slug}")
    assert public.status_code == 200
    assert public.json()["company"]["theme"] == {"radius": "sharp"}


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_branding_validation(client: AsyncClient) -> None:
    await _register_admin(client)
    for bad in (
        {"primary_color": "7E14FF"},
        {"primary_color": "#7E14"},
        {"primary_color": "#7E14FG"},
        {"radius": "pill"},
    ):
        resp = await client.patch("/api/v1/company/branding", json=bad)
        assert resp.status_code == 422, bad


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_branding_is_admin_only(client: AsyncClient) -> None:
    await _register_admin(client)
    member_email = f"member-{uuid4().hex[:8]}@vetd-ci.dev"
    member_pw = "member-password-1234"
    resp = await client.post(
        "/api/v1/users", json={"email": member_email, "password": member_pw, "role": "member"}
    )
    assert resp.status_code == 201, resp.text
    await client.post("/api/v1/auth/logout")
    resp = await client.post(
        "/api/v1/auth/login", json={"email": member_email, "password": member_pw}
    )
    assert resp.status_code == 200
    assert (await client.get("/api/v1/company")).status_code == 403
    assert (
        await client.patch("/api/v1/company/branding", json={"radius": "round"})
    ).status_code == 403
