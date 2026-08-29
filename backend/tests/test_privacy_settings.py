"""Privacy settings (M5.6 G1): PATCH /company/settings privacy keys +
the public privacy-notice payload with server-side fallbacks."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.services.company import RETENTION_DEFAULT_MONTHS
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)

NOTICE_FIELDS = {
    "company_name",
    "legal_name",
    "privacy_contact_email",
    "retention_months",
    "privacy_policy_url",
    "brand_primary",
    "logo_url",
}


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _register_admin(client: AsyncClient) -> tuple[str, str]:
    name = f"Privacy Co {uuid4().hex[:6]}"
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": name,
            "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
            "password": "a-long-secure-password",
        },
    )
    assert resp.status_code == 201, resp.text
    return name, name.lower().replace(" ", "-")


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_privacy_settings_roundtrip(client: AsyncClient) -> None:
    _, slug = await _register_admin(client)

    resp = await client.patch(
        "/api/v1/company/settings",
        json={
            "legal_name": "Privacy Co Sp. z o.o.",
            "privacy_contact_email": "privacy@ganek-ci.dev",
            "retention_months": 12,
            "privacy_policy_url": "https://example.com/privacy",
        },
    )
    assert resp.status_code == 200, resp.text
    stored = resp.json()["settings"]
    assert stored["legal_name"] == "Privacy Co Sp. z o.o."
    assert stored["privacy_contact_email"] == "privacy@ganek-ci.dev"
    assert stored["retention_months"] == 12
    # HttpUrl must land in JSONB as a plain string
    assert stored["privacy_policy_url"] == "https://example.com/privacy"

    # partial patch touches only the sent key
    resp = await client.patch("/api/v1/company/settings", json={"retention_months": 3})
    assert resp.json()["settings"]["retention_months"] == 3
    assert resp.json()["settings"]["legal_name"] == "Privacy Co Sp. z o.o."

    # explicit null resets a key to the default
    resp = await client.patch("/api/v1/company/settings", json={"legal_name": None})
    assert "legal_name" not in resp.json()["settings"]

    # the public notice reflects the stored values (with legal_name fallback)
    notice = (await client.get(f"/api/v1/public/companies/{slug}/privacy")).json()
    assert notice["legal_name"] == notice["company_name"]
    assert notice["retention_months"] == 3
    assert notice["privacy_policy_url"] == "https://example.com/privacy"


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_privacy_settings_validation(client: AsyncClient) -> None:
    await _register_admin(client)
    for bad in (
        {"retention_months": 0},
        {"retention_months": 25},
        {"privacy_contact_email": "not-an-email"},
        {"privacy_policy_url": "not a url"},
        {"legal_name": ""},
        {"legal_name": "x" * 201},
    ):
        resp = await client.patch("/api/v1/company/settings", json=bad)
        assert resp.status_code == 422, bad


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_privacy_notice_defaults_and_no_settings_leak(client: AsyncClient) -> None:
    name, slug = await _register_admin(client)
    # internal settings key set — must never surface publicly
    resp = await client.patch("/api/v1/company/settings", json={"quiz_expired_reissue": "auto"})
    assert resp.status_code == 200

    notice = await client.get(f"/api/v1/public/companies/{slug}/privacy")
    assert notice.status_code == 200, notice.text
    body = notice.json()
    assert set(body) == NOTICE_FIELDS
    assert body["company_name"] == name
    assert body["legal_name"] == name  # fallback to display name
    assert body["privacy_contact_email"] is None
    assert body["retention_months"] == RETENTION_DEFAULT_MONTHS
    assert body["privacy_policy_url"] is None


@pytest.mark.usefixtures("migrated_db")
async def test_single_mode_privacy_notice(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mode", "multi")
    await _register_admin(client)
    await client.post("/api/v1/auth/logout")

    monkeypatch.setattr(settings, "mode", "single")
    resp = await client.get("/api/v1/public/company/privacy")
    assert resp.status_code == 200
    assert set(resp.json()) == NOTICE_FIELDS


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_privacy_settings_admin_only(client: AsyncClient) -> None:
    await _register_admin(client)
    member_email = f"member-{uuid4().hex[:8]}@ganek-ci.dev"
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
    assert (
        await client.patch("/api/v1/company/settings", json={"retention_months": 6})
    ).status_code == 403
