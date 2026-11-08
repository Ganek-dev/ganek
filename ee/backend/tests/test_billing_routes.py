"""Checkout, portal and the billing summary (card B1c), plus when billing
switches on. The Stripe client is the FakeGateway: no network."""

import uuid

import pytest
from conftest import Harness

from app.core.config import settings
from app.models.company import Company, CompanyPlan
from ganek_ee.billing.api import router
from ganek_ee.billing.config import PRICE_ENV, stripe_config_from_env
from ganek_ee.billing.store import AccountView
from ganek_ee.plans import UPGRADE_URL_ENV, HostedPolicy


def test_checkout_creates_the_customer_once_and_uses_the_env_price(harness: Harness) -> None:
    response = harness.client.post(
        "/api/v1/billing/checkout", json={"plan": "team", "interval": "year"}
    )
    assert response.status_code == 200
    assert response.json() == {"url": "https://checkout.stripe.test/session"}
    assert harness.gateway.customers_created == [
        {"company_id": str(harness.company.id), "name": "Acme", "email": "admin@acme.test"}
    ]
    checkout = harness.gateway.checkouts[0]
    assert checkout["customer_id"] == "cus_1"
    assert checkout["price_id"] == "price_team_y"
    base = settings.public_base_url.rstrip("/")
    assert checkout["success_url"] == f"{base}/admin/billing?checkout=success"
    assert checkout["cancel_url"] == f"{base}/admin/billing"

    # an abandoned Checkout retried later reuses the same Stripe customer
    again = harness.client.post("/api/v1/billing/checkout", json={"plan": "starter"})
    assert again.status_code == 200
    assert len(harness.gateway.customers_created) == 1
    assert harness.gateway.checkouts[1]["price_id"] == "price_starter_m"


def test_checkout_refuses_a_second_live_subscription(harness: Harness) -> None:
    harness.store.accounts[harness.company.id] = AccountView(
        harness.company.id, "cus_acme", "sub_1", "past_due", None
    )
    response = harness.client.post("/api/v1/billing/checkout", json={"plan": "team"})
    assert response.status_code == 409
    assert "billing portal" in response.json()["detail"]
    assert harness.gateway.checkouts == []


def test_checkout_rejects_free_and_unknown_plans(harness: Harness) -> None:
    for plan in ("free", "self_hosted", "enterprise"):
        response = harness.client.post("/api/v1/billing/checkout", json={"plan": plan})
        assert response.status_code == 422


def test_portal_needs_a_customer(harness: Harness) -> None:
    assert harness.client.post("/api/v1/billing/portal").status_code == 409
    harness.store.accounts[harness.company.id] = AccountView(
        harness.company.id, "cus_acme", "sub_1", "active", None
    )
    response = harness.client.post("/api/v1/billing/portal")
    assert response.status_code == 200
    assert response.json() == {"url": "https://billing.stripe.test/portal"}
    assert harness.gateway.portals[0]["customer_id"] == "cus_acme"


def test_billing_summary(harness: Harness) -> None:
    assert harness.client.get("/api/v1/billing").json() == {
        "plan": "free",
        "status": None,
        "current_period_end": None,
        "can_manage": False,
        "trial_ends_at": None,
        "can_start_trial": True,
    }
    harness.store.accounts[harness.company.id] = AccountView(
        harness.company.id, "cus_acme", "sub_1", "active", None
    )
    assert harness.client.get("/api/v1/billing").json()["can_manage"] is True


def test_config_is_all_or_nothing(stripe_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    config = stripe_config_from_env()
    assert config is not None
    assert config.plan_for_price("price_team_m") is CompanyPlan.TEAM
    assert config.plan_for_price("price_unknown") is None
    monkeypatch.delenv("STRIPE_PRICE_TEAM_ANNUAL")  # one missing price = billing off
    assert stripe_config_from_env() is None


def _company() -> Company:
    return Company(id=uuid.uuid4(), slug="acme", name="Acme", plan=CompanyPlan.FREE)


def test_policy_without_stripe_keeps_billing_off(monkeypatch: pytest.MonkeyPatch) -> None:
    for env in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", *PRICE_ENV.values()):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv(UPGRADE_URL_ENV, "https://ganek.io/pricing")
    policy = HostedPolicy()
    assert policy.billing_enabled is False
    assert list(policy.routers()) == []
    assert policy.upgrade_url(_company()) == "https://ganek.io/pricing"


def test_policy_with_stripe_mounts_billing_and_links_the_page(
    stripe_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(UPGRADE_URL_ENV, "https://ganek.io/pricing")
    policy = HostedPolicy()
    assert policy.billing_enabled is True
    assert list(policy.routers()) == [router]
    base = settings.public_base_url.rstrip("/")
    assert policy.upgrade_url(_company()) == f"{base}/admin/billing"


def test_subscription_view_reads_both_api_shapes() -> None:
    """Newer Stripe API versions moved current_period_end onto the items."""
    from ganek_ee.billing.gateway import subscription_view

    old = subscription_view(
        {
            "id": "sub_1",
            "status": "active",
            "created": 5,
            "current_period_end": 1_800_000_000,
            "items": {"data": [{"price": {"id": "price_team_m"}}]},
        }
    )
    new = subscription_view(
        {
            "id": "sub_1",
            "status": "active",
            "created": 5,
            "items": {
                "data": [{"price": {"id": "price_team_m"}, "current_period_end": 1_800_000_000}]
            },
        }
    )
    assert old == new
    assert old.price_ids == ("price_team_m",)
    assert old.current_period_end is not None
    assert old.current_period_end.year == 2027
