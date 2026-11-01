import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models import ActivityLog, Company, Interview, InterviewStatus, Scorecard, User, UserRole
from app.schemas.users import UserCreate, UserUpdate
from app.services import activity, scorecards


class EmailTakenError(Exception):
    """A user with this email already exists."""


class LastAdminError(Exception):
    """Refuses to remove the company's last active admin."""


class HasUpcomingInterviewsError(Exception):
    """Refuses to anonymize an interviewer with active/upcoming interviews."""


async def list_users(db: AsyncSession, company: Company) -> list[User]:
    return list(
        (
            await db.execute(
                select(User)
                .where(
                    User.company_id == company.id,
                    # anonymized tombstones stay in the table (interviews FK)
                    # but are nobody's teammate anymore
                    ~User.email.like("deleted-%@invalid"),
                )
                .order_by(User.created_at)
            )
        )
        .scalars()
        .all()
    )


async def get_user(db: AsyncSession, company: Company, user_id: uuid.UUID) -> User | None:
    return (
        await db.execute(select(User).where(User.company_id == company.id, User.id == user_id))
    ).scalar_one_or_none()


async def create_user(db: AsyncSession, company: Company, payload: UserCreate) -> User:
    taken = (
        await db.execute(select(func.count()).select_from(User).where(User.email == payload.email))
    ).scalar_one()
    if taken:
        raise EmailTakenError
    user = User(
        company_id=company.id,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    await db.commit()
    return user


async def _active_admin_count(db: AsyncSession, company: Company) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(User)
            .where(
                User.company_id == company.id,
                User.role == UserRole.ADMIN,
                User.is_active.is_(True),
            )
        )
    ).scalar_one()


async def update_user(db: AsyncSession, company: Company, user: User, payload: UserUpdate) -> User:
    """Apply role/active changes, protecting the last active admin.

    Demoting or deactivating the only remaining admin is refused so a
    company can never lock itself out.
    """
    demoting_admin = user.role is UserRole.ADMIN and (
        (payload.role is not None and payload.role is not UserRole.ADMIN)
        or payload.is_active is False
    )
    if demoting_admin and await _active_admin_count(db, company) <= 1:
        raise LastAdminError
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
        if payload.is_active is False:
            # kill the deactivated user's live sessions immediately
            user.token_version += 1
    await db.commit()
    await db.refresh(user)
    return user


async def _relabel_scorecard_activity(
    db: AsyncSession, company: Company, user: User, label: str
) -> None:
    """The timeline reads reviewer_label from the frozen activity payload, so
    the anonymised reviewer's name must be rewritten there too. Rows are found
    through the user's own scorecards; other reviewers' rows on the same
    application keep their label."""
    app_ids = (
        (
            await db.execute(
                select(Scorecard.application_id).where(
                    Scorecard.company_id == company.id, Scorecard.reviewer_user_id == user.id
                )
            )
        )
        .scalars()
        .all()
    )
    if not app_ids:
        return
    rows = (
        (
            await db.execute(
                select(ActivityLog).where(
                    ActivityLog.company_id == company.id,
                    ActivityLog.application_id.in_(app_ids),
                    ActivityLog.type.like("scorecard.%"),
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        if row.payload.get("reviewer_label") == label:
            row.payload = {**row.payload, "reviewer_label": "Former teammate"}


async def anonymize_user(
    db: AsyncSession, company: Company, user: User, *, actor_user_id: uuid.UUID | None
) -> None:
    """GDPR removal for staff accounts, in place.

    interviews.interviewer_user_id has no ondelete, so a hard DELETE is
    FK-blocked for anyone who ever interviewed. Instead: tombstone the
    email, drop every credential, wipe the availability pattern and
    deactivate - the row survives for the FK, the person is gone.
    """
    if (
        user.is_active
        and user.role is UserRole.ADMIN
        and await _active_admin_count(db, company) <= 1
    ):
        raise LastAdminError
    upcoming = (
        await db.execute(
            select(Interview.id)
            .where(
                Interview.interviewer_user_id == user.id,
                Interview.status != InterviewStatus.CANCELLED,
                or_(
                    Interview.scheduled_start.is_(None),
                    Interview.scheduled_start > datetime.now(UTC),
                ),
            )
            .limit(1)
        )
    ).first()
    if upcoming is not None:
        raise HasUpcomingInterviewsError
    # open scorecard requests die with the person (activity scorecard.dismissed,
    # actor = the admin); the label they froze into the activity payloads is
    # captured now, before the tombstone changes what display_label says
    label = user.display_label
    await scorecards.dismiss_open_for_reviewer(db, user, actor_user_id=actor_user_id)
    await _relabel_scorecard_activity(db, company, user, label)
    user.email = f"deleted-{uuid.uuid4().hex}@invalid"  # emails are globally unique
    user.display_name = None
    user.password_hash = None
    user.google_sub = None
    user.interview_availability = None  # a tombstone offers no slots
    user.interview_location = None
    user.is_active = False
    user.token_version += 1  # kill live sessions immediately
    activity.record(
        db,
        company_id=company.id,
        type=activity.USER_ANONYMIZED,
        actor_user_id=actor_user_id,
        application_id=None,
        payload={},
    )
    await db.commit()
