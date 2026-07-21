"""Seed the database with the bundled question bank.

Upserts by stable question id: new questions are inserted, existing ones
updated in place (so re-seeding on upgrade applies edits and retirements
without duplicating). Questions absent from the YAML are left untouched.

Run: ``python -m app.services.seed`` (the compose migrate service does).
"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import SessionFactory
from app.models import Question, QuestionSource

logger = logging.getLogger(__name__)


def questions_dir() -> Path | None:
    if settings.questions_dir is not None:
        path = Path(settings.questions_dir)
        return path if path.is_dir() else None
    here = Path(__file__).resolve()
    # repo checkout: <repo>/backend/app/services/seed.py → <repo>/questions
    # docker image:   /srv/app/services/seed.py → /srv/questions (compose mount)
    for base in (here.parents[3], here.parents[2]):
        candidate = base / "questions"
        if candidate.is_dir():
            return candidate
    return None


@dataclass
class SeedReport:
    created: int = 0
    updated: int = 0
    unchanged: int = 0


_FIELDS = (
    "domain",
    "tags",
    "difficulty",
    "prompt_md",
    "options",
    "correct_key",
    "explanation_md",
    "time_limit_seconds",
    "locale",
    "status",
)


def _to_row(pack: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    tags = [pack["tag"], *item.get("tags", [])]
    return {
        "domain": pack["domain"],
        "tags": sorted(set(tags)),
        "difficulty": item["difficulty"],
        "prompt_md": item["prompt"],
        "options": dict(item["options"]),
        "correct_key": item["correct"],
        "explanation_md": item.get("explanation", "").strip(),
        "time_limit_seconds": item.get("time_limit_seconds", 15),
        "locale": item.get("locale", "en"),
        "status": item.get("status", "active"),
    }


async def seed_questions(db: AsyncSession, directory: Path) -> SeedReport:
    report = SeedReport()
    for path in sorted(directory.glob("*/*.yaml")):
        pack = yaml.safe_load(path.read_text())
        for item in pack.get("questions", []):
            row = _to_row(pack, item)
            existing = (
                await db.execute(select(Question).where(Question.id == item["id"]))
            ).scalar_one_or_none()
            if existing is None:
                db.add(Question(id=item["id"], source=QuestionSource.SEED, **row))
                report.created += 1
                continue
            changed = False
            for field, value in row.items():
                current = getattr(existing, field)
                current = current.value if hasattr(current, "value") else current
                if current != value:
                    setattr(existing, field, value)
                    changed = True
            if changed:
                report.updated += 1
            else:
                report.unchanged += 1
    await db.commit()
    return report


async def run() -> None:
    directory = questions_dir()
    if directory is None:
        logger.warning("question bank directory not found; skipping question seeding")
        return
    async with SessionFactory() as db:
        report = await seed_questions(db, directory)
    logger.info(
        "question bank seeded from %s: %d created, %d updated, %d unchanged",
        directory,
        report.created,
        report.updated,
        report.unchanged,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
