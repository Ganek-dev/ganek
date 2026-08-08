from collections.abc import Callable
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Company, User, UserRole
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


def _register_payload(**overrides: str) -> dict[str, str]:
    payload = {
        "company_name": f"Acme {uuid4().hex[:6]}",
        "email": f"admin-{uuid4().hex[:8]}@vetd-ci.dev",
        "password": "a-long-secure-password",
    }
    payload.update(overrides)
    return payload


MultiMode = Callable[[], None]


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_register_login_me_logout_flow(client: AsyncClient) -> None:
    payload = _register_payload()

    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == payload["email"]
    assert body["role"] == "admin"
    assert "password" not in body and "password_hash" not in body

    # session cookie from register works
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["email"] == payload["email"]

    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 204
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401

    # fresh login
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert resp.status_code == 200
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 200


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_login_rejects_wrong_password(client: AsyncClient) -> None:
    payload = _register_payload()
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": "definitely-wrong-password"},
    )
    assert resp.status_code == 401


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_register_rejects_duplicate_email(client: AsyncClient) -> None:
    payload = _register_payload()
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201
    resp = await client.post(
        "/api/v1/auth/register", json=_register_payload(email=payload["email"])
    )
    assert resp.status_code == 409


@pytest.mark.usefixtures("migrated_db")
async def test_single_mode_registration_closes_after_first_company(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mode", "multi")
    assert (await client.post("/api/v1/auth/register", json=_register_payload())).status_code == 201
    # DB now has >=1 company; single mode must refuse further registrations
    monkeypatch.setattr(settings, "mode", "single")
    resp = await client.post("/api/v1/auth/register", json=_register_payload())
    assert resp.status_code == 409


async def test_me_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


@pytest.mark.usefixtures("migrated_db")
async def test_password_login_rejects_google_only_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company = Company(slug=f"go-{uuid4().hex[:8]}", name="Google Only Co")
    db_session.add(company)
    await db_session.flush()
    email = f"go-{uuid4().hex[:8]}@gmail.com"
    user = User(
        company_id=company.id,
        email=email,
        password_hash=None,
        role=UserRole.ADMIN,
        google_sub=f"sub-{uuid4().hex}",
    )
    db_session.add(user)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "whatever-long"}
    )
    assert resp.status_code == 401
