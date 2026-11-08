import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ErasureTombstone(Base):
    """Blind marker that an application, candidate or whole tenant was
    erased (Art. 17).

    Holds only SHA-256 of the erased row's random UUID: no PII, nothing
    enumerable, so the table can live in every backup. A restore of an
    older dump brings erased rows back; ``services.tombstones.replay``
    erases them again by matching their hashes (restore.sh runs it).
    """

    __tablename__ = "erasure_tombstones"

    subject_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # application | candidate | company
    # SET NULL: a deleted tenant's tombstones outlive the company row (0052)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
