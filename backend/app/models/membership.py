import uuid
from typing import Any

from sqlalchemy import Enum, ForeignKey, UniqueConstraint, func, inspect
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection
from sqlalchemy.event import listens_for
from sqlalchemy.orm import Mapped, Mapper, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.user import User, UserRole


class CompanyMembership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One person's seat in one company, with the role they hold there
    (0056, card "SSO + multi-company user membership").

    Slice 1 of the card: the table exists and mirrors ``users.company_id`` /
    ``users.role`` exactly, one row per user, kept in sync by the mapper
    listeners below on every insert and every role or company change. Nothing
    reads it yet; the tenancy dependency still resolves the company from
    ``users.company_id``. The follow-up slices move tenancy onto this table
    (active company from the session), add the company switcher and lift the
    one-company-per-email limit.
    """

    __tablename__ = "company_memberships"
    __table_args__ = (UniqueConstraint("user_id", "company_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, values_callable=lambda e: [m.value for m in e], native_enum=False, length=20)
    )


def _upsert_membership(connection: Connection, user: User) -> None:
    role = UserRole(user.role)
    connection.execute(
        pg_insert(CompanyMembership)
        .values(id=uuid.uuid4(), user_id=user.id, company_id=user.company_id, role=role)
        .on_conflict_do_update(
            index_elements=["user_id", "company_id"],
            set_={"role": role, "updated_at": func.now()},
        )
    )


@listens_for(User, "after_insert")
def _membership_for_new_user(_mapper: Mapper[Any], connection: Connection, user: User) -> None:
    _upsert_membership(connection, user)


@listens_for(User, "after_update")
def _membership_follows_user(_mapper: Mapper[Any], connection: Connection, user: User) -> None:
    state = inspect(user)
    if state.attrs.role.history.has_changes() or state.attrs.company_id.history.has_changes():
        _upsert_membership(connection, user)
