"""google_calendar service tests — Google's HTTP surface is faked throughout."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import decrypt_secret
from app.models import Company, User, UserRole
from app.services import google_calendar
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any] | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeAsyncClient:
    """Stands in for httpx.AsyncClient; the next response is set per test."""

    next_response: FakeResponse = FakeResponse(200)
    calls: list[dict[str, Any]] = []

    def __init__(self, **kwargs: Any) -> None: ...

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, **kwargs: Any) -> FakeResponse:
        FakeAsyncClient.calls.append({"method": "POST", "url": url, **kwargs})
        return FakeAsyncClient.next_response

    async def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        FakeAsyncClient.calls.append({"method": method, "url": url, **kwargs})
        return FakeAsyncClient.next_response


@pytest.fixture(autouse=True)
def _reset_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeAsyncClient.next_response = FakeResponse(200)
    FakeAsyncClient.calls = []
    google_calendar._token_cache.clear()
    google_calendar._freebusy_cache.clear()
    monkeypatch.setattr(google_calendar.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "test-client-secret")


async def _make_user(db: AsyncSession) -> User:
    company = Company(slug=f"gcal-{uuid4().hex[:8]}", name="GCal Co")
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=f"gcal-{uuid4().hex[:8]}@gmail.com",
        password_hash="x",
        role=UserRole.ADMIN,
    )
    db.add(user)
    await db.commit()
    return user


@pytest.mark.usefixtures("migrated_db")
async def test_store_encrypts_and_roundtrips(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    await google_calendar.store_credentials(
        db_session, user, refresh_token="1//raw-refresh", google_email="me@gmail.com"
    )
    credential = await google_calendar.get_credential(db_session, user)
    assert credential is not None
    assert "1//raw-refresh" not in credential.refresh_token_encrypted
    assert decrypt_secret(credential.refresh_token_encrypted) == "1//raw-refresh"
    assert credential.google_email == "me@gmail.com"
    assert credential.last_refresh_error is None


@pytest.mark.usefixtures("migrated_db")
async def test_access_token_happy_path(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    await google_calendar.store_credentials(
        db_session, user, refresh_token="1//r", google_email="me@gmail.com"
    )
    FakeAsyncClient.next_response = FakeResponse(200, {"access_token": "ya29.token"})
    assert await google_calendar.access_token(db_session, user) == "ya29.token"
    sent = FakeAsyncClient.calls[-1]
    assert sent["data"]["grant_type"] == "refresh_token"
    assert sent["data"]["refresh_token"] == "1//r"


@pytest.mark.usefixtures("migrated_db")
async def test_access_token_invalid_grant_stamps_reconnect(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    await google_calendar.store_credentials(
        db_session, user, refresh_token="1//r", google_email="me@gmail.com"
    )
    FakeAsyncClient.next_response = FakeResponse(400, {}, text='{"error": "invalid_grant"}')
    with pytest.raises(google_calendar.NeedsReconnectError):
        await google_calendar.access_token(db_session, user)
    credential = await google_calendar.get_credential(db_session, user)
    assert credential is not None
    assert credential.last_refresh_error == "invalid_grant"


@pytest.mark.usefixtures("migrated_db")
async def test_access_token_without_credential_raises(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    with pytest.raises(google_calendar.NeedsReconnectError):
        await google_calendar.access_token(db_session, user)


@pytest.mark.usefixtures("migrated_db")
async def test_remove_credentials_revokes_and_deletes(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    await google_calendar.store_credentials(
        db_session, user, refresh_token="1//r", google_email="me@gmail.com"
    )
    await google_calendar.remove_credentials(db_session, user)
    assert await google_calendar.get_credential(db_session, user) is None
    revoke = [c for c in FakeAsyncClient.calls if c["url"] == google_calendar.REVOKE_ENDPOINT]
    assert revoke and revoke[0]["data"]["token"] == "1//r"


@pytest.mark.usefixtures("migrated_db")
async def test_create_meet_event_sends_conference_request(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _make_user(db_session)

    async def fake_token(db: AsyncSession, u: User) -> str:
        return "ya29.token"

    monkeypatch.setattr(google_calendar, "access_token", fake_token)
    FakeAsyncClient.next_response = FakeResponse(
        200, {"id": "evt-1", "hangoutLink": "https://meet.google.com/abc"}
    )
    event_id, meet = await google_calendar.create_meet_event(
        db_session,
        user,
        summary="Hiring manager interview",
        description="Your work, our stack.",
        start=datetime(2026, 8, 12, 14, 0, tzinfo=UTC),
        end=datetime(2026, 8, 12, 14, 45, tzinfo=UTC),
        attendee_email="cand@x.dev",
        timezone="Europe/Berlin",
    )
    assert (event_id, meet) == ("evt-1", "https://meet.google.com/abc")
    sent = FakeAsyncClient.calls[-1]
    assert sent["params"]["sendUpdates"] == "all"
    assert sent["json"]["conferenceData"]["createRequest"]["conferenceSolutionKey"] == {
        "type": "hangoutsMeet"
    }
    assert sent["json"]["attendees"] == [{"email": "cand@x.dev"}]


@pytest.mark.usefixtures("migrated_db")
async def test_freebusy_parses_windows(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _make_user(db_session)

    async def fake_token(db: AsyncSession, u: User) -> str:
        return "ya29.token"

    monkeypatch.setattr(google_calendar, "access_token", fake_token)
    FakeAsyncClient.next_response = FakeResponse(
        200,
        {
            "calendars": {
                "primary": {
                    "busy": [
                        {"start": "2026-08-12T10:00:00+00:00", "end": "2026-08-12T11:00:00+00:00"}
                    ]
                }
            }
        },
    )
    windows = await google_calendar.freebusy(
        db_session,
        user,
        datetime(2026, 8, 12, tzinfo=UTC),
        datetime(2026, 8, 13, tzinfo=UTC),
    )
    assert windows == [
        (
            datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
            datetime(2026, 8, 12, 11, 0, tzinfo=UTC),
        )
    ]


@pytest.mark.usefixtures("migrated_db")
async def test_delete_event_swallows_gone(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _make_user(db_session)

    async def fake_token(db: AsyncSession, u: User) -> str:
        return "ya29.token"

    monkeypatch.setattr(google_calendar, "access_token", fake_token)
    FakeAsyncClient.next_response = FakeResponse(404)
    await google_calendar.delete_event(db_session, user, "evt-gone")  # must not raise


@pytest.mark.usefixtures("migrated_db")
async def test_access_token_is_cached_until_expiry(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M5.7 H4: one refresh per ~hour, not one per calendar call."""
    user = await _make_user(db_session)
    await google_calendar.store_credentials(
        db_session, user, refresh_token="1//r", google_email="me@gmail.com"
    )
    FakeAsyncClient.calls = []  # drop the connect-time noise
    FakeAsyncClient.next_response = FakeResponse(
        200, {"access_token": "ya29.one", "expires_in": 3600}
    )
    assert await google_calendar.access_token(db_session, user) == "ya29.one"
    assert await google_calendar.access_token(db_session, user) == "ya29.one"
    assert len(FakeAsyncClient.calls) == 1  # second hit came from the cache

    # a revoked grant clears the cache so the reconnect card is honest
    google_calendar._token_cache[user.id] = ("ya29.stale", 0.0)  # force refresh
    FakeAsyncClient.next_response = FakeResponse(400, {}, text="invalid_grant")
    with pytest.raises(google_calendar.NeedsReconnectError):
        await google_calendar.access_token(db_session, user)
    assert user.id not in google_calendar._token_cache


@pytest.mark.usefixtures("migrated_db")
async def test_freebusy_is_cached_within_ttl(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC as _UTC
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    user = await _make_user(db_session)
    await google_calendar.store_credentials(
        db_session, user, refresh_token="1//r", google_email="me@gmail.com"
    )

    async def fake_token(db: AsyncSession, u: User) -> str:
        return "ya29.x"

    monkeypatch.setattr(google_calendar, "access_token", fake_token)
    start = _dt.now(_UTC) + _td(hours=1)
    end = start + _td(days=14)
    FakeAsyncClient.calls = []
    FakeAsyncClient.next_response = FakeResponse(
        200,
        {
            "calendars": {
                "primary": {
                    "busy": [
                        {"start": start.isoformat(), "end": (start + _td(hours=1)).isoformat()}
                    ]
                }
            }
        },
    )
    first = await google_calendar.freebusy(db_session, user, start, end)
    assert len(first) == 1
    # a moment later the horizon slid forward — the padded cache still covers
    second = await google_calendar.freebusy(
        db_session, user, start + _td(seconds=20), end + _td(seconds=20)
    )
    assert second == first
    assert len([c for c in FakeAsyncClient.calls if "freeBusy" in str(c["url"])]) == 1

    # creating an event invalidates: the next freebusy asks Google again
    FakeAsyncClient.next_response = FakeResponse(
        200, {"id": "evt-1", "conferenceData": {"entryPoints": []}}
    )
    await google_calendar.create_meet_event(
        db_session,
        user,
        summary="s",
        description="",
        start=start,
        end=start + _td(minutes=30),
        timezone="Europe/Berlin",
        attendee_email="c@x.dev",
    )
    FakeAsyncClient.next_response = FakeResponse(200, {"calendars": {"primary": {"busy": []}}})
    third = await google_calendar.freebusy(db_session, user, start, end)
    assert third == []
