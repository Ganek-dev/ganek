import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.company import Company


class Questionnaire(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A recruiter-curated ordered set of questions.

    ``question_refs`` stores the question identifiers as strings so both
    open-bank slug ids (``py-gil-1``) and company-question UUIDs live in
    one column. Order is authoritative unless ``shuffle`` is true; the
    quiz engine wires the resolution and integrity checks in a follow-up.
    """

    __tablename__ = "questionnaires"
    __table_args__ = (UniqueConstraint("company_id", "name"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(500), default="")
    shuffle: Mapped[bool] = mapped_column(default=False)
    question_refs: Mapped[list[str]] = mapped_column(ARRAY(String(100)), default=list)
    # Free-form curator metadata (badges, notes for the builder) — kept
    # opt-in so schema evolutions don't need a migration each time.
    meta: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)

    company: Mapped["Company"] = relationship()
