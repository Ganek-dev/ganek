from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Application,
    ApplicationStage,
    Candidate,
    Company,
    Job,
    User,
    UserRole,
)
from app.models.scorecard import Recommendation
from app.services import email as email_service
from app.services import scorecards as svc
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
TEMPLATE = [
    {"id": "aaaa1111", "label": "Problem solving", "hint": ""},
    {"id": "bbbb2222", "label": "Communication", "hint": ""},
]


class Env:
    def __init__(self, company: Company, job: Job, app: Application, admin: User, member: User):
        self.company, self.job, self.app, self.admin, self.member = company, job, app, admin, member


def _user(company: Company, role: UserRole, tag: str) -> User:
    return User(
        company_id=company.id,
        email=f"{tag}-{uuid4().hex[:8]}@sc.dev",
        password_hash="x",
        role=role,
    )


async def _env(db: AsyncSession) -> Env:
    company = Company(slug=f"sc-{uuid4().hex[:8]}", name="Sc Co")
    db.add(company)
    await db.flush()
    job = Job(
        company_id=company.id,
        slug="dev",
        title="Dev",
        scorecard_template=[dict(c) for c in TEMPLATE],
    )
    candidate = Candidate(company_id=company.id, email=f"c-{uuid4().hex[:8]}@x.dev", name="Marta")
    admin = _user(company, UserRole.ADMIN, "admin")
    member = _user(company, UserRole.MEMBER, "member")
    db.add_all([job, candidate, admin, member])
    await db.flush()
    app = Application(
        company_id=company.id,
        job_id=job.id,
        candidate_id=candidate.id,
        cv_object_key=f"cvs/{uuid4().hex}.pdf",
        cv_filename="cv.pdf",
        cv_size=1,
    )
    db.add(app)
    await db.commit()
    return Env(company, job, app, admin, member)


@pytest.fixture
def mails(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict[str, Any]]]:
    sent: dict[str, list[dict[str, Any]]] = {"request": [], "reminder": []}
    monkeypatch.setattr(
        email_service, "send_scorecard_request", lambda **kw: sent["request"].append(kw)
    )
    monkeypatch.setattr(
        email_service, "send_scorecard_reminder", lambda **kw: sent["reminder"].append(kw)
    )
    return sent


async def _activity(db: AsyncSession, env: Env, type_: str) -> list[Any]:
    from sqlalchemy import select

    from app.models import ActivityLog

    return list(
        (
            await db.execute(
                select(ActivityLog).where(
                    ActivityLog.company_id == env.company.id, ActivityLog.type == type_
                )
            )
        ).scalars()
    )


@pytest.mark.usefixtures("migrated_db")
async def test_request_creates_open_row_with_snapshot_and_mail(
    db_session: AsyncSession, mails: dict[str, list[dict[str, Any]]]
) -> None:
    env = await _env(db_session)
    row = await svc.request(
        db_session, application=env.app, reviewer=env.member, requested_by=env.admin, now=NOW
    )
    await db_session.commit()
    assert svc.state_of(row) == "open"
    assert row.due_from == NOW
    assert row.criteria_snapshot == TEMPLATE
    assert row.job_id == env.job.id
    assert len(mails["request"]) == 1
    mail = mails["request"][0]
    assert mail["to"] == env.member.email
    assert mail["url"].endswith(f"?selected={env.app.id}&scorecard=1")
    assert mail["candidate_name"] == "Marta"
    acts = await _activity(db_session, env, "scorecard.requested")
    assert len(acts) == 1
    assert acts[0].payload == {"reviewer_label": env.member.display_label}


@pytest.mark.usefixtures("migrated_db")
async def test_request_twice_raises_already_open(
    db_session: AsyncSession, mails: dict[str, list[dict[str, Any]]]
) -> None:
    env = await _env(db_session)
    await svc.request(db_session, application=env.app, reviewer=env.member, requested_by=env.admin)
    with pytest.raises(svc.AlreadyOpenError):
        await svc.request(
            db_session, application=env.app, reviewer=env.member, requested_by=env.admin
        )


@pytest.mark.usefixtures("migrated_db")
async def test_request_self_raises(
    db_session: AsyncSession, mails: dict[str, list[dict[str, Any]]]
) -> None:
    env = await _env(db_session)
    with pytest.raises(svc.SelfRequestError):
        await svc.request(
            db_session, application=env.app, reviewer=env.member, requested_by=env.member
        )


@pytest.mark.usefixtures("migrated_db")
async def test_request_from_booking_sends_no_mail_and_uses_due_from(
    db_session: AsyncSession, mails: dict[str, list[dict[str, Any]]]
) -> None:
    env = await _env(db_session)
    end = NOW + timedelta(days=1)
    row = await svc.request(
        db_session,
        application=env.app,
        reviewer=env.member,
        requested_by=None,
        interview_id=None,
        due_from=end,
        notify=False,
        now=NOW,
    )
    assert row.due_from == end
    assert mails["request"] == []


@pytest.mark.usefixtures("migrated_db")
async def test_snapshot_survives_template_edit(
    db_session: AsyncSession, mails: dict[str, list[dict[str, Any]]]
) -> None:
    env = await _env(db_session)
    row = await svc.request(
        db_session, application=env.app, reviewer=env.member, requested_by=env.admin, now=NOW
    )
    env.job.scorecard_template = [{"id": "cccc3333", "label": "New", "hint": ""}]
    await db_session.commit()
    with pytest.raises(ValueError):
        await svc.submit(
            db_session,
            row,
            ratings={"cccc3333": 3},
            recommendation=Recommendation.YES,
            comment=None,
        )
    out = await svc.submit(
        db_session,
        row,
        ratings={"aaaa1111": 3},
        recommendation=Recommendation.YES,
        comment=None,
        now=NOW,
    )
    assert out.ratings == {"aaaa1111": 3}


@pytest.mark.usefixtures("migrated_db")
async def test_submit_validates_and_records_once(
    db_session: AsyncSession, mails: dict[str, list[dict[str, Any]]]
) -> None:
    env = await _env(db_session)
    row = await svc.request(
        db_session, application=env.app, reviewer=env.member, requested_by=env.admin, now=NOW
    )
    await db_session.commit()
    for bad in (0, 5):
        with pytest.raises(ValueError):
            await svc.submit(
                db_session,
                row,
                ratings={"aaaa1111": bad},
                recommendation=Recommendation.YES,
                comment=None,
                now=NOW,
            )
    await svc.submit(
        db_session,
        row,
        ratings={"aaaa1111": 4},
        recommendation=Recommendation.YES,
        comment="first",
        now=NOW,
    )
    await db_session.commit()
    assert row.submitted_at == NOW
    assert svc.state_of(row) == "submitted"
    first_updated = row.updated_at
    await svc.submit(
        db_session,
        row,
        ratings={"aaaa1111": 4},
        recommendation=Recommendation.STRONG_YES,
        comment="second",
        now=NOW + timedelta(hours=2),
    )
    await db_session.commit()
    assert row.comment == "second"
    assert row.submitted_at == NOW
    assert row.updated_at >= first_updated
    assert len(await _activity(db_session, env, "scorecard.submitted")) == 1
    with pytest.raises(svc.EditWindowClosedError):
        await svc.submit(
            db_session,
            row,
            ratings={},
            recommendation=Recommendation.NO,
            comment=None,
            now=NOW + timedelta(hours=25),
        )


@pytest.mark.usefixtures("migrated_db")
async def test_decline_and_dismiss_require_open(
    db_session: AsyncSession, mails: dict[str, list[dict[str, Any]]]
) -> None:
    env = await _env(db_session)
    row = await svc.request(
        db_session, application=env.app, reviewer=env.member, requested_by=env.admin, now=NOW
    )
    await svc.decline(db_session, row, now=NOW)
    assert svc.state_of(row) == "declined"
    with pytest.raises(svc.NotOpenError):
        await svc.dismiss(db_session, row, actor_user_id=env.admin.id, now=NOW)
    with pytest.raises(svc.NotOpenError):
        await svc.decline(db_session, row, now=NOW)


@pytest.mark.usefixtures("migrated_db")
async def test_reopen_after_decline_resets_everything(
    db_session: AsyncSession, mails: dict[str, list[dict[str, Any]]]
) -> None:
    env = await _env(db_session)
    row = await svc.request(
        db_session, application=env.app, reviewer=env.member, requested_by=env.admin, now=NOW
    )
    row.ratings = {"aaaa1111": 2}
    row.comment = "stale"
    row.reminded_at = NOW
    await svc.decline(db_session, row, now=NOW)
    await db_session.commit()
    env.job.scorecard_template = [{"id": "dddd4444", "label": "Fresh", "hint": ""}]
    again = await svc.request(
        db_session,
        application=env.app,
        reviewer=env.member,
        requested_by=env.admin,
        now=NOW + timedelta(days=1),
    )
    assert again.id == row.id
    assert again.declined_at is None
    assert again.ratings == {}
    assert again.recommendation is None
    assert again.comment is None
    assert again.reminded_at is None
    assert again.criteria_snapshot == [{"id": "dddd4444", "label": "Fresh", "hint": ""}]
    assert len(mails["request"]) == 2
    assert len(await _activity(db_session, env, "scorecard.requested")) == 2


def test_waiting_days_uses_utc_dates() -> None:
    from app.models.scorecard import Scorecard

    row = Scorecard(due_from=datetime(2026, 11, 2, 23, 30, tzinfo=UTC))
    assert svc.waiting_days(row, now=datetime(2026, 11, 3, 0, 10, tzinfo=UTC)) == 1
    assert svc.waiting_days(row, now=datetime(2026, 11, 2, 23, 59, tzinfo=UTC)) == 0
    assert svc.waiting_days(row, now=datetime(2026, 11, 1, 1, 0, tzinfo=UTC)) == 0


def test_reviewer_label_for_missing_user() -> None:
    assert svc.reviewer_label(None) == "Former teammate"


@pytest.mark.usefixtures("migrated_db")
async def test_due_for_reminder_filters(
    db_session: AsyncSession, mails: dict[str, list[dict[str, Any]]]
) -> None:
    env = await _env(db_session)
    users = [_user(env.company, UserRole.MEMBER, f"r{i}") for i in range(6)]
    db_session.add_all(users)
    await db_session.flush()
    rows = []
    for i, u in enumerate(users):
        days = 2 if i == 0 else 3
        rows.append(
            await svc.request(
                db_session,
                application=env.app,
                reviewer=u,
                requested_by=env.admin,
                due_from=NOW - timedelta(days=days),
                notify=False,
                now=NOW,
            )
        )
    rows[2].reminded_at = NOW - timedelta(days=1)
    users[4].is_active = False
    await svc.dismiss(db_session, rows[5], actor_user_id=None, now=NOW)
    await db_session.commit()
    # rows[0]: 2 days, rows[1]: due, rows[2]: reminded, rows[3]: due (later rejected
    # on a second application below), rows[4]: inactive, rows[5]: dismissed
    due = await svc.due_for_reminder(db_session, now=NOW)
    ours = {r.id for r in due if r.company_id == env.company.id}
    assert ours == {rows[1].id, rows[3].id}
    env.app.stage = ApplicationStage.REJECTED
    await db_session.commit()
    due = await svc.due_for_reminder(db_session, now=NOW)
    assert not [r for r in due if r.company_id == env.company.id]
    env.app.stage = ApplicationStage.NEW
    await db_session.commit()
    await svc.mark_reminded(db_session, [rows[1]], now=NOW)
    await db_session.commit()
    assert rows[1].reminded_at == NOW
    due = await svc.due_for_reminder(db_session, now=NOW)
    assert {r.id for r in due if r.company_id == env.company.id} == {rows[3].id}


@pytest.mark.usefixtures("migrated_db")
async def test_submitted_row_is_not_due(
    db_session: AsyncSession, mails: dict[str, list[dict[str, Any]]]
) -> None:
    env = await _env(db_session)
    row = await svc.request(
        db_session,
        application=env.app,
        reviewer=env.member,
        requested_by=env.admin,
        due_from=NOW - timedelta(days=5),
        notify=False,
        now=NOW,
    )
    await svc.submit(
        db_session, row, ratings={}, recommendation=Recommendation.YES, comment=None, now=NOW
    )
    await db_session.commit()
    due = await svc.due_for_reminder(db_session, now=NOW)
    assert not [r for r in due if r.company_id == env.company.id]


@pytest.mark.usefixtures("migrated_db")
async def test_list_mine_orders_and_filters(
    db_session: AsyncSession, mails: dict[str, list[dict[str, Any]]]
) -> None:
    env = await _env(db_session)
    apps = [env.app]
    for _ in range(3):
        cand = Candidate(company_id=env.company.id, email=f"c-{uuid4().hex[:8]}@x.dev", name="K")
        db_session.add(cand)
        await db_session.flush()
        a = Application(
            company_id=env.company.id,
            job_id=env.job.id,
            candidate_id=cand.id,
            cv_object_key=f"cvs/{uuid4().hex}.pdf",
            cv_filename="cv.pdf",
            cv_size=1,
        )
        db_session.add(a)
        apps.append(a)
    await db_session.flush()
    rows = []
    for i, a in enumerate(apps):
        rows.append(
            await svc.request(
                db_session,
                application=a,
                reviewer=env.member,
                requested_by=env.admin,
                due_from=NOW + timedelta(hours=i),
                notify=False,
                now=NOW,
            )
        )
    await svc.submit(
        db_session, rows[0], ratings={}, recommendation=Recommendation.YES, comment=None, now=NOW
    )
    await svc.decline(db_session, rows[1], now=NOW)
    await svc.dismiss(db_session, rows[2], actor_user_id=env.admin.id, now=NOW)
    await db_session.commit()
    open_rows = await svc.list_mine(db_session, user=env.member, state="open")
    assert [r.id for r in open_rows] == [rows[3].id]
    all_rows = await svc.list_mine(db_session, user=env.member, state="all")
    assert [r.id for r in all_rows] == [rows[3].id, rows[1].id, rows[0].id]
    mine = await svc.get_mine(db_session, user=env.member, application_id=apps[0].id)
    assert mine is not None and mine.id == rows[0].id
    assert await svc.get_mine(db_session, user=env.admin, application_id=apps[0].id) is None
    listed = await svc.list_for_application(
        db_session, company_id=env.company.id, application_id=apps[0].id
    )
    assert [r.id for r in listed] == [rows[0].id]
    assert await svc.dismiss_open_for_reviewer(db_session, env.member, actor_user_id=None) == 1
