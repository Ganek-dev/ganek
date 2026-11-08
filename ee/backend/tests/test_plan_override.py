"""Operator plan override (Q21, card "Operator plane: superadmin plan
override"). No database: the policy reads the override off the billing row
the company carries, and the SQL store's webhook write runs against a
recording session double, so a replayed webhook is shown to leave the
override alone."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from conftest import Harness, subscription

from app.core.plans import PoweredBy
from app.models import BillingAccount
from app.models.company import Company, CompanyPlan
from ganek_ee import plans as hosted_plans
from ganek_ee.billing.store import AccountView, SqlBillingStore
from ganek_ee.billing.sync import BillingState
from ganek_ee.plans import HostedPolicy

T0 = datetime(2026, 11, 8, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hosted_plans, "now", lambda: T0)


def _company(
    plan: CompanyPlan, override: CompanyPlan | None, trial_ends_at: datetime | None = None
) -> Company:
    company = Company(id=uuid.uuid4(), slug="acme", name="Acme", plan=plan)
    company.billing_account = BillingAccount(
        company_id=company.id, plan_override=override, trial_ends_at=trial_ends_at
    )
    return company


def test_override_to_team_lifts_the_free_limit_and_the_badge() -> None:
    policy = HostedPolicy()
    company = _company(CompanyPlan.FREE, CompanyPlan.TEAM)
    assert policy.limits(company).max_live_jobs is None
    assert policy.can_publish(company, live_jobs=7) is True
    assert policy.powered_by(company) is PoweredBy.NONE


def test_override_wins_over_a_paid_plan_and_a_running_trial() -> None:
    policy = HostedPolicy()
    down = _company(CompanyPlan.TEAM, CompanyPlan.FREE)
    assert policy.limits(down).max_live_jobs == 1
    assert policy.powered_by(down) is PoweredBy.BADGE
    trialing = _company(CompanyPlan.FREE, CompanyPlan.STARTER, T0 + timedelta(days=5))
    assert policy.limits(trialing).max_live_jobs == 5
    # the override decides alone: no trial is reported as running
    assert policy.trial_ends_at(trialing) is None


def test_no_override_keeps_the_synced_plan() -> None:
    policy = HostedPolicy()
    assert policy.limits(_company(CompanyPlan.STARTER, None)).max_live_jobs == 5
    loose = Company(id=uuid.uuid4(), slug="acme", name="Acme", plan=CompanyPlan.FREE)
    assert policy.limits(loose).max_live_jobs == 1


class _RecordingSession:
    """Just enough of AsyncSession for SqlBillingStore.apply."""

    def __init__(self, row: BillingAccount, company: Company) -> None:
        self.row = row
        self.company = company
        self.commits = 0

    async def scalar(self, _stmt: Any) -> BillingAccount:
        return self.row

    async def get(self, _model: Any, _id: Any) -> Company:
        return self.company

    async def commit(self) -> None:
        self.commits += 1


def test_a_replayed_webhook_write_leaves_the_override_in_place() -> None:
    company = Company(id=uuid.uuid4(), slug="acme", name="Acme", plan=CompanyPlan.FREE)
    row = BillingAccount(
        company_id=company.id, stripe_customer_id="cus_acme", plan_override=CompanyPlan.TEAM
    )
    session = _RecordingSession(row, company)
    store = SqlBillingStore(session)  # type: ignore[arg-type]
    deleted = BillingState(
        plan=CompanyPlan.FREE, subscription_id=None, status="canceled", current_period_end=None
    )
    for _ in range(2):  # Stripe delivers the same event twice
        asyncio.run(store.apply(company.id, deleted))
    assert session.commits == 2
    assert company.plan is CompanyPlan.FREE  # the synced plan follows Stripe
    assert row.plan_override is CompanyPlan.TEAM  # the override stays
    company.billing_account = row
    assert HostedPolicy().limits(company).max_live_jobs is None


def test_webhook_route_replays_keep_the_override(harness: Harness) -> None:
    harness.store.accounts[harness.company.id] = AccountView(
        harness.company.id, "cus_acme", None, None, None
    )
    harness.company.billing_account = BillingAccount(
        company_id=harness.company.id, plan_override=CompanyPlan.TEAM
    )
    harness.gateway.subscriptions["cus_acme"] = [subscription("sub_1", "canceled")]
    for _ in range(2):
        assert harness.webhook("customer.subscription.deleted", "cus_acme").status_code == 200
    harness.company.plan = harness.store.plans[harness.company.id]
    assert harness.company.plan is CompanyPlan.FREE
    assert HostedPolicy().limits(harness.company).max_live_jobs is None
