import logging
import uuid
from dataclasses import dataclass
from typing import Any

import pytest

from app.core import plans
from app.core.plans import UNLIMITED, SelfHostedPolicy, load_plan_policy
from app.models import Company, CompanyPlan


@dataclass
class _FakeEntryPoint:
    value: str
    target: Any

    def load(self) -> Any:
        return self.target


class _StubHosted:
    name = "stub_hosted"
    billing_enabled = True


def _install(monkeypatch: pytest.MonkeyPatch, *eps: _FakeEntryPoint) -> None:
    def fake_entry_points(*, group: str) -> list[_FakeEntryPoint]:
        assert group == plans.ENTRY_POINT_GROUP
        return list(eps)

    monkeypatch.setattr(plans, "entry_points", fake_entry_points)


def _company() -> Company:
    return Company(id=uuid.uuid4(), slug="acme", name="Acme", plan=CompanyPlan.FREE)


def test_self_hosted_policy_has_no_limits() -> None:
    policy = SelfHostedPolicy()
    company = _company()
    assert policy.billing_enabled is False
    assert policy.limits(company) == UNLIMITED
    assert policy.can_publish(company, live_jobs=10_000) is True
    assert policy.upgrade_url(company) is None


def test_community_edition_ignores_installed_ee(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _FakeEntryPoint("ganek_ee.plans:HostedPolicy", _StubHosted))
    assert isinstance(load_plan_policy("community"), SelfHostedPolicy)


def test_hosted_without_ee_warns_and_falls_back(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _install(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="app.core.plans"):
        policy = load_plan_policy("hosted")
    assert isinstance(policy, SelfHostedPolicy)
    assert "no ganek.plan_policy entry point" in caplog.text


def test_hosted_loads_the_ee_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _FakeEntryPoint("ganek_ee.plans:HostedPolicy", _StubHosted))
    assert load_plan_policy("hosted").name == "stub_hosted"


def test_hosted_refuses_two_policies(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        _FakeEntryPoint("a:Policy", _StubHosted),
        _FakeEntryPoint("b:Policy", _StubHosted),
    )
    with pytest.raises(RuntimeError, match="more than one"):
        load_plan_policy("hosted")


def test_default_edition_is_community() -> None:
    assert plans.settings.edition == "community"
    assert isinstance(plans.get_plan_policy(), SelfHostedPolicy)


def test_self_hosted_signups_stay_self_hosted() -> None:
    assert SelfHostedPolicy().signup_plan is CompanyPlan.SELF_HOSTED


class _OneJob:
    name = "one_job"
    billing_enabled = True
    signup_plan = CompanyPlan.FREE

    def limits(self, company: Company) -> plans.PlanLimits:
        return plans.PlanLimits(max_live_jobs=1)

    def can_publish(self, company: Company, live_jobs: int) -> bool:
        return live_jobs < 1

    def upgrade_url(self, company: Company) -> str | None:
        return "https://example.test/upgrade"


def test_ensure_can_publish_allows_under_the_limit() -> None:
    plans.ensure_can_publish(_OneJob(), _company(), live_jobs=0)
    plans.ensure_can_publish(SelfHostedPolicy(), _company(), live_jobs=10_000)


def test_ensure_can_publish_raises_with_the_402_payload() -> None:
    with pytest.raises(plans.PlanLimitExceeded) as caught:
        plans.ensure_can_publish(_OneJob(), _company(), live_jobs=1)
    detail = caught.value.detail()
    assert detail["code"] == "plan_limit"
    assert detail["limit"] == 1
    assert detail["upgrade_url"] == "https://example.test/upgrade"
    assert detail["message"] == (
        "Your plan allows 1 live job. Close a job or upgrade the plan to publish another."
    )
