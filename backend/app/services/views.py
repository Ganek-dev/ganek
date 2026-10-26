"""Job page view counters (spec job posts v2 5.5, decisions JP1/JP8).

The Next.js server render decides whether a load is a countable view (no
recruiter session, no preview, no prefetch, no bot) and says so with two
request headers on its backend fetch. This module turns that into one
``INSERT ... ON CONFLICT DO UPDATE SET views = views + 1`` per (job, UTC
day, source). Advisory by decision: the headers are forgeable through the
public API, so the source is re-validated against the one grammar and a
(job, day) keeps at most 50 distinct sources; the rest fold into ``other``.
Nothing per visitor is ever stored.
"""

import logging
import uuid
from datetime import UTC, date, datetime

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from app.core.sources import normalize_source
from app.models import JobView

log = logging.getLogger(__name__)

VIEW_HEADER = "x-ganek-view"
SOURCE_HEADER = "x-ganek-source"
MAX_SOURCES_PER_DAY = 50
OTHER = "other"
DIRECT = "direct"


def wants_view(request: Request) -> bool:
    """The SSR marked this load as a countable view (exactly ``1``)."""
    return request.headers.get(VIEW_HEADER) == "1"


def view_source(raw: str | None) -> str:
    """The grammar-checked source for a view; anything odd is ``direct`` (a
    view is still a view). ``other`` is a fold label, never accepted here."""
    return normalize_source(raw) or DIRECT


def today() -> date:
    return datetime.now(UTC).date()


def is_open_ended(source: str) -> bool:
    """``link:<name>`` and ``ref:<host>`` are chosen by whoever sends them;
    only those count against the daily source budget."""
    return source.startswith(("link:", "ref:"))


async def record_view(
    db: AsyncSession, job_id: uuid.UUID, source: str, day: date | None = None
) -> str:
    """Add one view to (job, day, source) and commit. Returns the stored
    label: ``source``, or ``other`` for a new ``link:`` / ``ref:`` name once
    the day already holds ``MAX_SOURCES_PER_DAY`` distinct ones. ``direct``
    and the known buckets never fold: a spam run must not turn real
    traffic into ``other`` (review focus 2)."""
    day = day or today()
    label = source
    if is_open_ended(source):
        existing = set(
            (
                await db.execute(
                    select(JobView.source).where(JobView.job_id == job_id, JobView.day == day)
                )
            ).scalars()
        )
        named = {s for s in existing if is_open_ended(s)}
        if source not in named and len(named) >= MAX_SOURCES_PER_DAY:
            label = OTHER
    stmt = (
        pg_insert(JobView)
        .values(job_id=job_id, day=day, source=label, views=1)
        .on_conflict_do_update(constraint="pk_job_views", set_={"views": JobView.views + 1})
    )
    await db.execute(stmt)
    await db.commit()
    return label


async def record_view_task(
    bind: AsyncEngine | AsyncConnection, job_id: uuid.UUID, source: str
) -> None:
    """Background-task entry point. FastAPI closes the request's session
    before background tasks run, so this opens its own on the same engine
    (which is also what lets tests hand in their per-test engine). A
    counter failure is logged and swallowed: it must never reach a
    candidate or a recruiter."""
    try:
        async with async_sessionmaker(bind, expire_on_commit=False)() as db:
            await record_view(db, job_id, source)
    except Exception:  # noqa: BLE001 - advisory counter, never fatal
        log.warning("job view not recorded for job %s", job_id, exc_info=True)
