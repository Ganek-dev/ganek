import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models import (
    ActivityLog,
    Company,
    CompanyMembership,
    Interview,
    InterviewStatus,
    Scorecard,
    User,
    UserRole,
)
from app.schemas.users import UserCreate, UserUpdate
from app.services import activity, scorecards


class EmailTakenError(Exception):
    """A user with this email already exists."""


class LastAdminError(Exception):
    """Refuses to remove the company's last active admin."""


class HasUpcomingInterviewsError(Exception):
    """Refuses to anonymize an interviewer with active/upcoming interviews."""


class SharedAccountError(Exception):
    """The person also holds a seat in another company, so an account-wide
    change (deactivate, anonymize) made from this company is refused."""


@dataclass(frozen=True)
class Teammate:
    """A user as one company sees them: the account plus the role of their
    seat in THAT company (card "SSO + multi-company user membership",
    slice 4). ``user.role`` is the role of the user's active seat, which can
    be another company's."""

    user: User
    role: UserRole


def _team_query(company: Company) -> Select[User, UserRole]:
    return (
        select(User, CompanyMembership.role)
        .join(CompanyMembership, CompanyMembership.user_id == User.id)
        .where(CompanyMembership.company_id == company.id)
    )


async def list_users(db: AsyncSession, company: Company) -> list[Teammate]:
    """Everyone with a seat in the company, whichever company is active for them."""
    rows = (
        await db.execute(
            _team_query(company)
            # anonymized tombstones stay in the table (interviews FK)
            # but are nobody's teammate anymore
            .where(~User.email.like("deleted-%@invalid"))
            .order_by(User.created_at)
        )
    ).all()
    return [Teammate(user=u, role=UserRole(r)) for u, r in rows]


async def get_user(db: AsyncSession, company: Company, user_id: uuid.UUID) -> Teammate | None:
    row = (await db.execute(_team_query(company).where(User.id == user_id))).one_or_none()
    return None if row is None else Teammate(user=row[0], role=UserRole(row[1]))


async def _has_other_seats(db: AsyncSession, company: Company, user: User) -> bool:
    return (
        await db.execute(
            select(CompanyMembership.id)
            .where(
                CompanyMembership.user_id == user.id,
                CompanyMembership.company_id != company.id,
            )
            .limit(1)
        )
    ).first() is not None


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
    """Active accounts holding an admin seat in the company, counted over
    memberships so an admin whose active seat is elsewhere still counts."""
    return (
        await db.execute(
            select(func.count())
            .select_from(CompanyMembership)
            .join(User, User.id == CompanyMembership.user_id)
            .where(
                CompanyMembership.company_id == company.id,
                CompanyMembership.role == UserRole.ADMIN,
                User.is_active.is_(True),
            )
        )
    ).scalar_one()


async def update_user(
    db: AsyncSession, company: Company, mate: Teammate, payload: UserUpdate
) -> Teammate:
    """Apply role/active changes, protecting the last active admin.

    Demoting or deactivating the only remaining admin is refused so a
    company can never lock itself out. A role change moves only this
    company's seat. Deactivation is account-wide, so it is refused for a
    person who also belongs to another company.
    """
    user = mate.user
    toggling_active = payload.is_active is not None and payload.is_active != user.is_active
    if toggling_active and await _has_other_seats(db, company, user):
        raise SharedAccountError
    demoting_admin = mate.role is UserRole.ADMIN and (
        (payload.role is not None and payload.role is not UserRole.ADMIN)
        or payload.is_active is False
    )
    if demoting_admin and await _active_admin_count(db, company) <= 1:
        raise LastAdminError
    role = mate.role
    if payload.role is not None and payload.role is not mate.role:
        role = payload.role
        if user.company_id == company.id:
            # the active seat: the membership listener writes the row back
            user.role = payload.role
        else:
            seat = (
                await db.execute(
                    select(CompanyMembership).where(
                        CompanyMembership.user_id == user.id,
                        CompanyMembership.company_id == company.id,
                    )
                )
            ).scalar_one()
            seat.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
        if payload.is_active is False:
            # kill the deactivated user's live sessions immediately
            user.token_version += 1
    await db.commit()
    await db.refresh(user)
    return Teammate(user=user, role=role)


async def _relabel_scorecard_activity(db: AsyncSession, company: Company, user: User) -> None:
    """The timeline reads reviewer_label from the frozen activity payload, so
    the anonymised reviewer's name must be rewritten there too. Rows are keyed
    by the scorecard_id every scorecard.* payload carries, so renames and
    same-named colleagues cannot cause a miss or a collateral rewrite."""
    card_ids = [
        str(i)
        for i in (
            await db.execute(
                select(Scorecard.id).where(
                    Scorecard.company_id == company.id, Scorecard.reviewer_user_id == user.id
                )
            )
        )
        .scalars()
        .all()
    ]
    if not card_ids:
        return
    rows = (
        (
            await db.execute(
                select(ActivityLog).where(
                    ActivityLog.company_id == company.id,
                    ActivityLog.type.like("scorecard.%"),
                    ActivityLog.payload["scorecard_id"].astext.in_(card_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        if "reviewer_label" in row.payload:
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
    if await _has_other_seats(db, company, user):
        # erasure is account-wide: never wipe a person another company still has
        raise SharedAccountError
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
    # actor = the admin); their frozen label is then rewritten in the payloads
    await scorecards.dismiss_open_for_reviewer(
        db, user, actor_user_id=actor_user_id, company_id=company.id
    )
    await _relabel_scorecard_activity(db, company, user)
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
