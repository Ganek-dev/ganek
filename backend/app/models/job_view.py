import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class JobView(Base):
    """Daily page-view total for one job and one source label.

    Advisory counters (decision JP8): bumped by the public job GET when the
    server render says the load is a countable view. The row is the whole
    record: no IP, user agent, cookie, visitor id or sub-day time exists
    anywhere. ``source`` follows ``core/sources.py`` (or the literal
    ``other`` once a (job, day) has 50 distinct sources). Rows cascade
    with the job; readers always join ``Job`` under the tenancy dependency.
    """

    __tablename__ = "job_views"

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    source: Mapped[str] = mapped_column(String(100), primary_key=True)
    views: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
