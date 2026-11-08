"""BM3 limits of the hosted policy (card B1b). No database: the policy only
reads ``companies.plan`` off the company it is handed."""

import uuid

import pytest

from app.core.plans import PlanLimitExceeded, PoweredBy, ensure_can_publish
from app.models.company import Company, CompanyPlan
from ganek_ee.plans import UPGRADE_URL_ENV, HostedPolicy


def _company(plan: CompanyPlan) -> Company:
    return Company(id=uuid.uuid4(), slug="acme", name="Acme", plan=plan)


@pytest.mark.parametrize(
    ("plan", "limit"),
    [
        (CompanyPlan.FREE, 1),
        (CompanyPlan.STARTER, 5),
        (CompanyPlan.TEAM, None),
        (CompanyPlan.SELF_HOSTED, None),
    ],
)
def test_live_job_limits_follow_bm3(plan: CompanyPlan, limit: int | None) -> None:
    assert HostedPolicy().limits(_company(plan)).max_live_jobs == limit


def test_free_publishes_one_job_and_no_second() -> None:
    policy = HostedPolicy()
    free = _company(CompanyPlan.FREE)
    assert policy.can_publish(free, live_jobs=0) is True
    assert policy.can_publish(free, live_jobs=1) is False


def test_starter_stops_at_five_and_team_never() -> None:
    policy = HostedPolicy()
    assert policy.can_publish(_company(CompanyPlan.STARTER), live_jobs=4) is True
    assert policy.can_publish(_company(CompanyPlan.STARTER), live_jobs=5) is False
    assert policy.can_publish(_company(CompanyPlan.TEAM), live_jobs=10_000) is True


def test_over_the_limit_after_a_downgrade_stays_blocked() -> None:
    assert HostedPolicy().can_publish(_company(CompanyPlan.FREE), live_jobs=3) is False


def test_new_hosted_signups_start_on_free() -> None:
    assert HostedPolicy().signup_plan is CompanyPlan.FREE


def test_upgrade_url_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(UPGRADE_URL_ENV, raising=False)
    assert HostedPolicy().upgrade_url(_company(CompanyPlan.FREE)) is None
    monkeypatch.setenv(UPGRADE_URL_ENV, "https://ganek.io/pricing")
    assert HostedPolicy().upgrade_url(_company(CompanyPlan.FREE)) == "https://ganek.io/pricing"


def test_the_402_payload_carries_the_upgrade_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(UPGRADE_URL_ENV, "https://ganek.io/pricing")
    with pytest.raises(PlanLimitExceeded) as caught:
        ensure_can_publish(HostedPolicy(), _company(CompanyPlan.STARTER), live_jobs=5)
    assert caught.value.detail()["limit"] == 5
    assert caught.value.detail()["upgrade_url"] == "https://ganek.io/pricing"


@pytest.mark.parametrize(
    ("plan", "powered_by"),
    [
        (CompanyPlan.FREE, PoweredBy.BADGE),
        (CompanyPlan.STARTER, PoweredBy.NONE),
        (CompanyPlan.TEAM, PoweredBy.NONE),
        (CompanyPlan.SELF_HOSTED, PoweredBy.CREDIT),
    ],
)
def test_badge_is_required_on_free_and_removed_on_paid(
    plan: CompanyPlan, powered_by: PoweredBy
) -> None:
    assert HostedPolicy().powered_by(_company(plan)) is powered_by
