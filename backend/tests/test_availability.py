"""Availability schema validation + effective-availability resolution."""

from datetime import time
from uuid import uuid4

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.core.config import settings
from app.models import User, UserRole
from app.schemas.users import AvailabilityIn
from app.services import interviews as interviews_service
from tests.db import database_reachable


def _user(availability: dict | None) -> User:
    return User(
        company_id=None,  # never flushed — pure object
        email="dana@x.dev",
        password_hash="x",
        role=UserRole.MEMBER,
        interview_availability=availability,
    )


def test_availability_in_rejects_bad_windows() -> None:
    with pytest.raises(ValidationError):  # end before start
        AvailabilityIn(timezone="Europe/Berlin", days={"mon": {"start": "17:00", "end": "09:00"}})
    with pytest.raises(ValidationError):  # off the 30-min grid
        AvailabilityIn(timezone="Europe/Berlin", days={"mon": {"start": "09:15", "end": "17:00"}})
    with pytest.raises(ValidationError):  # unknown day key
        AvailabilityIn(
            timezone="Europe/Berlin", days={"monday": {"start": "09:00", "end": "17:00"}}
        )
    with pytest.raises(ValidationError):  # unknown zone
        AvailabilityIn(timezone="Mars/Olympus", days={})


def test_effective_availability_defaults_to_weekday_nine_to_five() -> None:
    tz, windows = interviews_service.effective_availability(_user(None))
    assert tz is None
    assert windows == {
        day: (time(9, 0), time(17, 0)) for day in ("mon", "tue", "wed", "thu", "fri")
    }


def test_effective_availability_reads_saved_schedule() -> None:
    saved = {
        "timezone": "Europe/Berlin",
        "days": {"tue": {"start": "10:00", "end": "16:00"}},
    }
    tz, windows = interviews_service.effective_availability(_user(saved))
    assert tz == "Europe/Berlin"
    assert windows == {"tue": (time(10, 0), time(16, 0))}


def test_effective_availability_skips_malformed_days() -> None:
    saved = {
        "timezone": "Europe/Berlin",
        "days": {
            "mon": {"start": "junk", "end": "17:00"},
            "wed": {"start": "09:00"},
            "fri": {"start": "09:00", "end": "12:00"},
        },
    }
    _, windows = interviews_service.effective_availability(_user(saved))
    assert windows == {"fri": (time(9, 0), time(12, 0))}


def test_summarize_availability_compresses_runs() -> None:
    _, windows = interviews_service.effective_availability(_user(None))
    assert interviews_service.summarize_availability(windows) == "Mon–Fri 09:00–17:00"
    ragged = {"mon": (time(9, 0), time(17, 0)), "fri": (time(9, 0), time(12, 0))}
    assert interviews_service.summarize_availability(ragged) == "Mon 09:00–17:00 · Fri 09:00–12:00"
    assert interviews_service.summarize_availability({}) == "no hours set"


api_marks = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _register(client: AsyncClient) -> None:
    creds = {"email": f"a-{uuid4().hex[:8]}@vetd-ci.dev", "password": "a-long-secure-password"}
    resp = await client.post(
        "/api/v1/auth/register", json={"company_name": f"Av Co {uuid4().hex[:6]}", **creds}
    )
    assert resp.status_code == 201, resp.text


@api_marks
@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_availability_roundtrip(client: AsyncClient) -> None:
    await _register(client)
    resp = await client.get("/api/v1/users/me/availability")
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_default"] is True
    assert body["days"]["mon"] == {"start": "09:00", "end": "17:00"}
    assert "sat" not in body["days"]

    payload = {
        "timezone": "Europe/Warsaw",
        "days": {"tue": {"start": "10:00", "end": "16:00"}},
    }
    resp = await client.put("/api/v1/users/me/availability", json=payload)
    assert resp.status_code == 200
    assert resp.json()["is_default"] is False

    body = (await client.get("/api/v1/users/me/availability")).json()
    assert body["timezone"] == "Europe/Warsaw"
    assert body["days"] == {"tue": {"start": "10:00", "end": "16:00"}}


@api_marks
@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_availability_put_validates(client: AsyncClient) -> None:
    await _register(client)
    resp = await client.put(
        "/api/v1/users/me/availability",
        json={"timezone": "Europe/Warsaw", "days": {"mon": {"start": "17:00", "end": "09:00"}}},
    )
    assert resp.status_code == 422
