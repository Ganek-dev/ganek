"""Erasure tombstones: make backups erasure-aware (board card A3).

Erasure receipts are count-only by design, so nothing in the database
said WHICH rows an older dump must not bring back. Every erased
application and candidate now leaves a tombstone holding SHA-256 of its
random UUID (blind: no PII, not enumerable). ``replay`` walks the live
rows, hashes their ids and erases the matches through the normal erasure
primitive (S3 first, fail-closed), so after ``scripts/restore.sh`` the
erased people stay erased. Idempotent; also runnable by hand:

    uv run python -m app.services.tombstones
"""

import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import asdict, dataclass

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models import Application, Candidate, ErasureTombstone

logger = logging.getLogger(__name__)

APPLICATION = "application"
CANDIDATE = "candidate"


def subject_hash(subject_id: uuid.UUID) -> str:
    return hashlib.sha256(subject_id.bytes).hexdigest()


async def record(
    db: AsyncSession, *, company_id: uuid.UUID, kind: str, subject_id: uuid.UUID
) -> None:
    """Stage a tombstone in the caller's transaction (no commit)."""
    await db.execute(
        insert(ErasureTombstone)
        .values(subject_hash=subject_hash(subject_id), kind=kind, company_id=company_id)
        .on_conflict_do_nothing(index_elements=["subject_hash"])
    )


@dataclass
class ReplaySummary:
    tombstones: int
    applications_erased: int
    candidates_erased: int
    storage_failures: int


async def replay(db: AsyncSession) -> ReplaySummary:
    """Erase every live row whose id hash has a tombstone. Commits."""
    from app.services import erasure  # local import: erasure records tombstones

    rows = (await db.execute(select(ErasureTombstone.subject_hash, ErasureTombstone.kind))).all()
    wanted = {row.subject_hash: row.kind for row in rows}
    summary = ReplaySummary(len(wanted), 0, 0, 0)
    if not wanted:
        return summary

    applications = (await db.execute(select(Application))).scalars().all()
    for application in applications:
        if wanted.get(subject_hash(application.id)) != APPLICATION:
            continue
        try:
            await erasure.erase_application(db, application)
        except Exception:  # noqa: BLE001 - storage down: keep the row, retry later
            logger.warning("tombstone replay: storage cleanup failed for %s", application.id)
            summary.storage_failures += 1
            continue
        summary.applications_erased += 1

    candidates = (await db.execute(select(Candidate))).scalars().all()
    for candidate in candidates:
        if wanted.get(subject_hash(candidate.id)) != CANDIDATE:
            continue
        # the candidate's applications were tombstoned with them; any that
        # survived a storage failure above stay for the next replay
        remaining = (
            await db.execute(select(Application.id).where(Application.candidate_id == candidate.id))
        ).first()
        if remaining is not None:
            continue
        await db.execute(delete(Candidate).where(Candidate.id == candidate.id))
        summary.candidates_erased += 1

    await db.commit()
    logger.info("tombstone replay: %s", summary)
    return summary


async def _main() -> None:
    from app.core.config import settings

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            summary = await replay(db)
    finally:
        await engine.dispose()
    print(json.dumps(asdict(summary)))  # noqa: T201 - CLI output for restore.sh


if __name__ == "__main__":
    asyncio.run(_main())
