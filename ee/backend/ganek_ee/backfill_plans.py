"""One-off operator backfill (card B1b, Q15): every hosted tenant that
existed before plans were enforced keeps working unmetered on Team. New
signups start on Free through HostedPolicy.signup_plan.

Run once on the hosted instance, from backend/:
    uv run --no-sync python -m ganek_ee.backfill_plans
Idempotent: only companies still on the 0050 default (self_hosted) move.
"""

import asyncio
import logging

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionFactory
from app.models.company import Company, CompanyPlan

logger = logging.getLogger(__name__)


async def backfill(db: AsyncSession) -> int:
    result = await db.execute(
        update(Company).where(Company.plan == CompanyPlan.SELF_HOSTED).values(plan=CompanyPlan.TEAM)
    )
    await db.commit()
    return int(result.rowcount or 0)


async def run() -> None:
    async with SessionFactory() as db:
        moved = await backfill(db)
    logger.info("plan backfill: %d companies moved from self_hosted to team", moved)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
