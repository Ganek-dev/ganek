"""Where the billing routes read and write ``billing_accounts`` and
``companies.plan``. The routes depend on the ``BillingStore`` protocol, so
the ee CI job (no database) runs them against an in-memory double; the SQL
store is the same four operations on the 0050 tables."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BillingAccount, Company
from ganek_ee.billing.sync import BillingState


@dataclass
class AccountView:
    company_id: uuid.UUID
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    status: str | None
    current_period_end: datetime | None


class BillingStore(Protocol):
    async def account(self, company_id: uuid.UUID) -> AccountView | None: ...

    async def save_customer(self, company_id: uuid.UUID, customer_id: str) -> None: ...

    async def company_for_customer(self, customer_id: str) -> uuid.UUID | None: ...

    async def apply(self, company_id: uuid.UUID, state: BillingState) -> None: ...


def _view(row: BillingAccount) -> AccountView:
    return AccountView(
        company_id=row.company_id,
        stripe_customer_id=row.stripe_customer_id,
        stripe_subscription_id=row.stripe_subscription_id,
        status=row.status,
        current_period_end=row.current_period_end,
    )


class SqlBillingStore:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def _row(self, company_id: uuid.UUID) -> BillingAccount | None:
        return await self._db.scalar(
            select(BillingAccount).where(BillingAccount.company_id == company_id)
        )

    async def account(self, company_id: uuid.UUID) -> AccountView | None:
        row = await self._row(company_id)
        return _view(row) if row else None

    async def save_customer(self, company_id: uuid.UUID, customer_id: str) -> None:
        row = await self._row(company_id)
        if row is None:
            row = BillingAccount(company_id=company_id)
            self._db.add(row)
        row.stripe_customer_id = customer_id
        await self._db.commit()

    async def company_for_customer(self, customer_id: str) -> uuid.UUID | None:
        return await self._db.scalar(
            select(BillingAccount.company_id).where(
                BillingAccount.stripe_customer_id == customer_id
            )
        )

    async def apply(self, company_id: uuid.UUID, state: BillingState) -> None:
        """One commit for the plan and the account row: a failure raises, the
        webhook answers 500 and Stripe retries (R1)."""
        row = await self._row(company_id)
        company = await self._db.get(Company, company_id)
        if row is None or company is None:
            raise LookupError(f"no billing account for company {company_id}")
        row.stripe_subscription_id = state.subscription_id
        row.status = state.status
        row.current_period_end = state.current_period_end
        company.plan = state.plan
        await self._db.commit()
