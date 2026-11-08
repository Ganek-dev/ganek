"""The 14-day Team trial without a card (card B1d, Q9). No database: the
policy reads the trial end off the billing row the company carries, the
routes run against the in-memory store, and the clock is frozen through
``ganek_ee.plans.now``."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from conftest import Harness

from app.core.plans import PlanLimitExceeded, ensure_can_publish
from app.models import BillingAccount
from app.models.company import Company, CompanyPlan
from ganek_ee import plans as hosted_plans
from ganek_ee.plans import HostedPolicy

T0 = datetime(2026, 11, 8, 9, 0, tzinfo=UTC)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[datetime]:
    """A frozen clock the test moves by assigning ``clock[0]``."""
    current = [T0]
    monkeypatch.setattr(hosted_plans, "now", lambda: current[0])
    return current


def _company(plan: CompanyPlan, trial_ends_at: datetime | None) -> Company:
    company = Company(id=uuid.uuid4(), slug="acme", name="Acme", plan=plan)
    company.billing_account = BillingAccount(company_id=company.id, trial_ends_at=trial_ends_at)
    return company


def test_a_running_trial_lets_free_publish_like_team(clock: list[datetime]) -> None:
    policy = HostedPolicy()
    company = _company(CompanyPlan.FREE, T0 + timedelta(days=14))
    assert policy.limits(company).max_live_jobs is None
    assert policy.can_publish(company, live_jobs=1) is True
    assert policy.can_publish(company, live_jobs=40) is True
    assert policy.trial_ends_at(company) == T0 + timedelta(days=14)


def test_after_the_trial_the_second_publish_is_refused_again(clock: list[datetime]) -> None:
    policy = HostedPolicy()
    company = _company(CompanyPlan.FREE, T0 + timedelta(days=14))
    clock[0] = T0 + timedelta(days=14, seconds=1)
    assert policy.limits(company).max_live_jobs == 1
    assert policy.trial_ends_at(company) is None
    # 3 jobs went live during the trial: none is closed, a 4th waits (Q8)
    assert policy.can_publish(company, live_jobs=3) is False
    with pytest.raises(PlanLimitExceeded) as raised:
        ensure_can_publish(policy, company, live_jobs=3)
    assert raised.value.limit == 1


def test_a_paid_plan_ignores_a_trial(clock: list[datetime]) -> None:
    policy = HostedPolicy()
    starter = _company(CompanyPlan.STARTER, T0 + timedelta(days=3))
    assert policy.limits(starter).max_live_jobs == 5
    assert policy.trial_ends_at(starter) is None


def test_no_billing_row_means_no_trial(clock: list[datetime]) -> None:
    policy = HostedPolicy()
    loose = Company(id=uuid.uuid4(), slug="acme", name="Acme", plan=CompanyPlan.FREE)
    assert policy.limits(loose).max_live_jobs == 1
    assert policy.trial_ends_at(loose) is None
    assert policy.limits(_company(CompanyPlan.FREE, None)).max_live_jobs == 1


def test_start_trial_once_then_refuse(harness: Harness, clock: list[datetime]) -> None:
    started = harness.client.post("/api/v1/billing/trial")
    assert started.status_code == 200, started.text
    body = started.json()
    assert datetime.fromisoformat(body["trial_ends_at"]) == T0 + timedelta(days=14)
    assert body["can_start_trial"] is False
    assert body["plan"] == "free"

    again = harness.client.post("/api/v1/billing/trial")
    assert again.status_code == 409
    assert "already used" in again.json()["detail"]
    # still the first end date, not a fresh 14 days
    assert harness.store.accounts[harness.company.id].trial_ends_at == T0 + timedelta(days=14)


def test_an_expired_trial_cannot_be_restarted(harness: Harness, clock: list[datetime]) -> None:
    assert harness.client.post("/api/v1/billing/trial").status_code == 200
    clock[0] = T0 + timedelta(days=30)
    summary = harness.client.get("/api/v1/billing").json()
    assert summary["trial_ends_at"] is None
    assert summary["can_start_trial"] is False
    assert harness.client.post("/api/v1/billing/trial").status_code == 409


def test_paid_companies_cannot_start_a_trial(harness: Harness, clock: list[datetime]) -> None:
    harness.company.plan = CompanyPlan.STARTER
    response = harness.client.post("/api/v1/billing/trial")
    assert response.status_code == 409
    assert "Free plan" in response.json()["detail"]
    assert harness.client.get("/api/v1/billing").json()["can_start_trial"] is False
