"""Decision date on the candidate status page: applied + the company's
decision window (Hiring settings), or the team's own date for one
application. A date, never a timestamp."""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Application, Company
from app.services import decision_dates
from tests.db import database_reachable, s3_reachable
from tests.test_attempt_reissue import _apply_with_quiz, _login_and_get_application

db_required = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


def _company(stored: dict[str, Any] | None) -> Company:
    return Company(name="x", slug="x", settings=stored)


def _application(created_at: datetime, override: date | None = None) -> Application:
    return Application(created_at=created_at, decision_expected_on=override)


# --- DB-free ----------------------------------------------------------------


def test_window_defaults_to_fourteen_days_and_ignores_junk() -> None:
    assert decision_dates.window_days(_company(None)) == 14
    assert decision_dates.window_days(_company({})) == 14
    assert decision_dates.window_days(_company({"decision_window_days": 21})) == 21
    for junk in (0, 91, -3, "10", True, 7.5):
        assert decision_dates.window_days(_company({"decision_window_days": junk})) == 14


def test_date_is_applied_day_plus_the_window() -> None:
    applied = datetime(2026, 10, 28, 9, 30, tzinfo=UTC)
    app = _application(applied)
    assert decision_dates.decision_expected_on(app, _company(None)) == date(2026, 11, 11)
    assert decision_dates.decision_expected_on(app, _company({"decision_window_days": 5})) == date(
        2026, 11, 2
    )


def test_applied_day_is_taken_in_utc() -> None:
    # 23:30 at UTC-5 is already the next day in UTC: one day, one answer
    from zoneinfo import ZoneInfo

    applied = datetime(2026, 10, 28, 23, 30, tzinfo=ZoneInfo("America/New_York"))
    app = _application(applied)
    assert decision_dates.applied_on(app) == date(2026, 10, 29)
    assert decision_dates.decision_expected_on(app, _company(None)) == date(2026, 11, 12)


def test_the_teams_own_date_wins_over_the_window() -> None:
    applied = datetime(2026, 10, 28, 9, 30, tzinfo=UTC)
    app = _application(applied, override=date(2026, 12, 1))
    assert decision_dates.decision_expected_on(app, _company({"decision_window_days": 3})) == date(
        2026, 12, 1
    )


def test_override_bounds() -> None:
    app = _application(datetime(2026, 10, 28, 9, 30, tzinfo=UTC))
    assert decision_dates.override_problem(app, date(2026, 10, 28)) is None
    assert decision_dates.override_problem(app, date(2027, 10, 28)) is None
    assert decision_dates.override_problem(app, date(2026, 10, 27)) is not None
    assert decision_dates.override_problem(app, date(2027, 10, 29)) is not None


# --- API ---------------------------------------------------------------------


@db_required
@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_status_page_follows_the_setting_and_the_per_application_date(
    client: AsyncClient,
) -> None:
    applied, creds = await _apply_with_quiz(client, with_quiz=False)
    status_url = f"/api/v1/public/applications/{applied['status_token']}"
    first = (await client.get(status_url)).json()
    applied_day = datetime.fromisoformat(first["applied_at"]).astimezone(UTC).date()
    assert first["decision_expected_by"] == (applied_day + timedelta(days=14)).isoformat()
    assert first["decision_overdue"] is False

    application = await _login_and_get_application(client, creds)
    assert application["decision_expected_on"] is None
    resp = await client.patch("/api/v1/company/settings", json={"decision_window_days": 30})
    assert resp.status_code == 200, resp.text
    assert (await client.get(status_url)).json()["decision_expected_by"] == (
        applied_day + timedelta(days=30)
    ).isoformat()

    own = (applied_day + timedelta(days=45)).isoformat()
    resp = await client.put(
        f"/api/v1/applications/{application['id']}/decision-date",
        json={"decision_expected_on": own},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["decision_expected_on"] == own
    assert (await client.get(status_url)).json()["decision_expected_by"] == own

    # null hands the date back to the setting
    resp = await client.put(
        f"/api/v1/applications/{application['id']}/decision-date",
        json={"decision_expected_on": None},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["decision_expected_on"] is None
    assert (await client.get(status_url)).json()["decision_expected_by"] == (
        applied_day + timedelta(days=30)
    ).isoformat()


@db_required
@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_decision_window_setting_range(client: AsyncClient) -> None:
    _, creds = await _apply_with_quiz(client, with_quiz=False)
    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    for bad in (0, 91):
        resp = await client.patch("/api/v1/company/settings", json={"decision_window_days": bad})
        assert resp.status_code == 422
    resp = await client.patch("/api/v1/company/settings", json={"decision_window_days": 10})
    assert resp.status_code == 200
    assert (await client.get("/api/v1/company")).json()["settings"]["decision_window_days"] == 10
    resp = await client.patch("/api/v1/company/settings", json={"decision_window_days": None})
    assert "decision_window_days" not in (await client.get("/api/v1/company")).json()["settings"]


@db_required
@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_decision_date_before_applying_is_refused(client: AsyncClient) -> None:
    _, creds = await _apply_with_quiz(client, with_quiz=False)
    application = await _login_and_get_application(client, creds)
    resp = await client.put(
        f"/api/v1/applications/{application['id']}/decision-date",
        json={"decision_expected_on": "2020-01-01"},
    )
    assert resp.status_code == 422
    assert "before the application" in resp.json()["detail"]


@db_required
@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_a_passed_date_reads_overdue_until_decided(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    applied, creds = await _apply_with_quiz(client, with_quiz=False)
    status_url = f"/api/v1/public/applications/{applied['status_token']}"
    application = await _login_and_get_application(client, creds)
    await db_session.execute(
        update(Application)
        .where(Application.id == UUID(str(application["id"])))
        .values(created_at=datetime.now(UTC) - timedelta(days=20))
    )
    await db_session.commit()
    assert (await client.get(status_url)).json()["decision_overdue"] is True

    resp = await client.patch(
        f"/api/v1/applications/{application['id']}/stage", json={"stage": "hired"}
    )
    assert resp.status_code == 200, resp.text
    assert (await client.get(status_url)).json()["decision_overdue"] is False
