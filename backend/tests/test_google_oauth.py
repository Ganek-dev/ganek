"""Google OAuth endpoints. Google's HTTP surface is monkeypatched throughout —
these tests exercise our flow handling, linking rules, and cookie handling."""

import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


@pytest.fixture
def google_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "test-client-secret")


async def test_providers_google_off_by_default(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/providers")
    assert resp.status_code == 200
    assert resp.json() == {"google": False}


@pytest.mark.usefixtures("google_configured")
async def test_providers_google_on_when_configured(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/providers")
    assert resp.json() == {"google": True}
