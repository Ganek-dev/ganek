"""Google Calendar for connected recruiters: token refresh, free/busy,
Meet-event CRUD.

Refresh tokens are Fernet-encrypted at rest (app/core/crypto.py) and are
never logged or serialized; access tokens live only in memory for the
duration of a request. A failed refresh grant (revoked consent, weekly
Testing-mode expiry) stamps last_refresh_error so the Account card can
show a reconnect prompt instead of breaking silently.
"""

import logging
import uuid as uuid_module
from datetime import UTC, datetime, time, timedelta
from time import monotonic
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.models import User, UserGoogleCredential
from app.services.oauth_google import GOOGLE_TOKEN_ENDPOINT

logger = logging.getLogger(__name__)

CALENDAR_API = "https://www.googleapis.com/calendar/v3"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"

# M5.7 H4 perf caches, both in-process (api and worker each keep their own).
# Access tokens are good for ~an hour — refreshing per call added a token-
# endpoint roundtrip in front of EVERY freebusy/event request. Free/busy is
# cached briefly per interviewer (SECURITY_REVIEW #5 mitigation: one hammered
# public booking link no longer burns per-client Google quota; book() also
# stops computing the same slot set twice).
_TOKEN_SAFETY_MARGIN_SECONDS = 300
_token_cache: dict[uuid_module.UUID, tuple[str, float]] = {}
FREEBUSY_TTL_SECONDS = 30.0
_FREEBUSY_PAD = timedelta(minutes=5)
_freebusy_cache: dict[
    uuid_module.UUID, tuple[datetime, datetime, list[tuple[datetime, datetime]], float]
] = {}


def _invalidate_caches(user_id: uuid_module.UUID) -> None:
    _token_cache.pop(user_id, None)
    _freebusy_cache.pop(user_id, None)


class GoogleCalendarError(Exception):
    """Google Calendar API failure that is not a consent problem."""


class NeedsReconnectError(GoogleCalendarError):
    """No usable credential — the user must (re)connect their calendar."""


async def get_credential(db: AsyncSession, user: User) -> UserGoogleCredential | None:
    return (
        await db.execute(
            select(UserGoogleCredential).where(UserGoogleCredential.user_id == user.id)
        )
    ).scalar_one_or_none()


async def store_credentials(
    db: AsyncSession, user: User, *, refresh_token: str, google_email: str
) -> None:
    """Upsert the (encrypted) refresh token; a reconnect replaces the old one."""
    _invalidate_caches(user.id)
    credential = await get_credential(db, user)
    if credential is None:
        credential = UserGoogleCredential(user_id=user.id)
        db.add(credential)
    credential.refresh_token_encrypted = encrypt_secret(refresh_token)
    credential.google_email = google_email
    credential.connected_at = datetime.now(UTC)
    credential.last_refresh_error = None
    await db.commit()


async def remove_credentials(db: AsyncSession, user: User) -> None:
    """Best-effort revoke at Google, then forget the credential."""
    credential = await get_credential(db, user)
    if credential is None:
        return
    token = decrypt_secret(credential.refresh_token_encrypted)
    if token is not None:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(REVOKE_ENDPOINT, data={"token": token})
        except httpx.HTTPError:
            logger.warning("google token revoke failed for user %s", user.id)
    await db.delete(credential)
    await db.commit()
    _invalidate_caches(user.id)


async def access_token(db: AsyncSession, user: User) -> str:
    """The user's Google access token — cached in-process until shortly
    before expiry, refreshed via the stored refresh token otherwise."""
    cached = _token_cache.get(user.id)
    if cached is not None and monotonic() < cached[1]:
        return cached[0]
    credential = await get_credential(db, user)
    if credential is None:
        raise NeedsReconnectError("google calendar is not connected")
    refresh_token = decrypt_secret(credential.refresh_token_encrypted)
    if refresh_token is None:
        raise NeedsReconnectError("stored credential is unreadable")
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.post(
                GOOGLE_TOKEN_ENDPOINT,
                data={
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        except httpx.HTTPError as exc:
            raise GoogleCalendarError("token endpoint unreachable") from exc
    if resp.status_code == 400 and "invalid_grant" in resp.text:
        credential.last_refresh_error = "invalid_grant"
        await db.commit()
        _invalidate_caches(user.id)
        raise NeedsReconnectError("google consent was revoked or expired")
    if resp.status_code != 200:
        raise GoogleCalendarError(f"token refresh failed with {resp.status_code}")
    body = resp.json()
    token = body.get("access_token")
    if not isinstance(token, str):
        raise GoogleCalendarError("no access_token in refresh response")
    expires_in = body.get("expires_in")
    ttl = (expires_in if isinstance(expires_in, int | float) else 3600) or 3600
    _token_cache[user.id] = (token, monotonic() + max(60.0, ttl - _TOKEN_SAFETY_MARGIN_SECONDS))
    return token


async def _google(
    db: AsyncSession,
    user: User,
    method: str,
    url: str,
    *,
    params: dict[str, str] | None = None,
    json: dict[str, Any] | None = None,
) -> httpx.Response:
    """One authenticated Calendar API call. Tests monkeypatch this."""
    token = await access_token(db, user)
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            return await client.request(
                method,
                url,
                params=params,
                json=json,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as exc:
            raise GoogleCalendarError("calendar api unreachable") from exc


async def freebusy(
    db: AsyncSession, user: User, start: datetime, end: datetime
) -> list[tuple[datetime, datetime]]:
    """Busy windows on the user's primary calendar between start and end (UTC).

    Cached briefly per user: the query window is padded so the cached range
    keeps covering follow-up requests whose "now"-anchored horizon slid
    forward within the TTL. Extra windows outside the asked range are
    harmless — every caller intersects.
    """
    start = start.astimezone(UTC)
    end = end.astimezone(UTC)
    cached = _freebusy_cache.get(user.id)
    if cached is not None:
        cached_start, cached_end, cached_busy, fetched_at = cached
        if (
            monotonic() - fetched_at < FREEBUSY_TTL_SECONDS
            and cached_start <= start
            and end <= cached_end
        ):
            return list(cached_busy)
    fetch_start = start - _FREEBUSY_PAD
    fetch_end = end + _FREEBUSY_PAD
    resp = await _google(
        db,
        user,
        "POST",
        f"{CALENDAR_API}/freeBusy",
        json={
            "timeMin": fetch_start.isoformat(),
            "timeMax": fetch_end.isoformat(),
            "items": [{"id": "primary"}],
        },
    )
    if resp.status_code != 200:
        raise GoogleCalendarError(f"freebusy failed with {resp.status_code}")
    busy = resp.json().get("calendars", {}).get("primary", {}).get("busy", [])
    windows: list[tuple[datetime, datetime]] = []
    for slot in busy:
        try:
            windows.append(
                (
                    datetime.fromisoformat(slot["start"]),
                    datetime.fromisoformat(slot["end"]),
                )
            )
        except (KeyError, ValueError):
            continue
    _freebusy_cache[user.id] = (fetch_start, fetch_end, windows, monotonic())
    return windows


async def create_meet_event(
    db: AsyncSession,
    user: User,
    *,
    summary: str,
    description: str,
    start: datetime,
    end: datetime,
    attendee_email: str,
    timezone: str,
) -> tuple[str, str | None]:
    """Create the interview event with a Meet link; Google emails the invite."""
    resp = await _google(
        db,
        user,
        "POST",
        f"{CALENDAR_API}/calendars/primary/events",
        params={"conferenceDataVersion": "1", "sendUpdates": "all"},
        json={
            "summary": summary,
            "description": description,
            "start": {"dateTime": start.isoformat(), "timeZone": timezone},
            "end": {"dateTime": end.isoformat(), "timeZone": timezone},
            "attendees": [{"email": attendee_email}],
            "conferenceData": {
                "createRequest": {
                    "requestId": uuid_module.uuid4().hex,
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
        },
    )
    if resp.status_code not in (200, 201):
        raise GoogleCalendarError(f"event create failed with {resp.status_code}")
    data = resp.json()
    event_id = data.get("id")
    if not isinstance(event_id, str):
        raise GoogleCalendarError("no event id in create response")
    meet = data.get("hangoutLink")
    _freebusy_cache.pop(user.id, None)  # the calendar just changed
    return event_id, meet if isinstance(meet, str) else None


async def patch_event_time(
    db: AsyncSession,
    user: User,
    event_id: str,
    *,
    start: datetime,
    end: datetime,
    timezone: str,
) -> None:
    resp = await _google(
        db,
        user,
        "PATCH",
        f"{CALENDAR_API}/calendars/primary/events/{event_id}",
        params={"sendUpdates": "all"},
        json={
            "start": {"dateTime": start.isoformat(), "timeZone": timezone},
            "end": {"dateTime": end.isoformat(), "timeZone": timezone},
        },
    )
    if resp.status_code != 200:
        raise GoogleCalendarError(f"event patch failed with {resp.status_code}")
    _freebusy_cache.pop(user.id, None)  # the calendar just changed


async def delete_event(db: AsyncSession, user: User, event_id: str) -> None:
    resp = await _google(
        db,
        user,
        "DELETE",
        f"{CALENDAR_API}/calendars/primary/events/{event_id}",
        params={"sendUpdates": "all"},
    )
    # already gone is fine — cancelling twice must not error
    if resp.status_code not in (204, 200, 404, 410):
        raise GoogleCalendarError(f"event delete failed with {resp.status_code}")
    _freebusy_cache.pop(user.id, None)  # the calendar just changed


async def list_today_events(db: AsyncSession, user: User, *, tz: str) -> list[dict[str, Any]]:
    """Today's events on the user's primary calendar, for the dashboard panel."""
    zone = ZoneInfo(tz)
    day = datetime.now(zone).date()
    time_min = datetime.combine(day, time.min, tzinfo=zone)
    time_max = datetime.combine(day, time.max, tzinfo=zone)
    resp = await _google(
        db,
        user,
        "GET",
        f"{CALENDAR_API}/calendars/primary/events",
        params={
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": "10",
        },
    )
    if resp.status_code != 200:
        raise GoogleCalendarError(f"events list failed with {resp.status_code}")
    events = []
    for item in resp.json().get("items", []):
        start = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date")
        events.append(
            {
                "start": start,
                "summary": item.get("summary") or "(no title)",
                "hangout_link": item.get("hangoutLink"),
            }
        )
    return events
