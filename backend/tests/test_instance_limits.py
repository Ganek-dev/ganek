"""GET /auth/providers also tells the signup page which per-tenant limits
this instance enforces (card B3: strangers see "what you get" before they
sign up). DB-free: the client engine connects lazily."""

import pytest
from httpx import AsyncClient

from app.core.config import settings


async def test_providers_lists_instance_limits(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "quota_active_jobs", 7)
    monkeypatch.setattr(settings, "quota_applications_per_hour", 0)
    monkeypatch.setattr(settings, "quota_emails_per_day", 300)
    resp = await client.get("/api/v1/auth/providers")
    assert resp.status_code == 200
    assert resp.json()["limits"] == {
        "active_jobs": 7,
        "applications_per_hour": 0,
        "emails_per_day": 300,
    }
