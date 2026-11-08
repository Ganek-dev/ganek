"""Stripe webhook (card B1c, R1): signature, the accepted event types, the
convergent sync by customer, replays and the 500 cases Stripe retries."""

import logging

import pytest
from conftest import Harness, subscription

from app.models.company import CompanyPlan
from ganek_ee.billing.store import AccountView


@pytest.fixture
def customer(harness: Harness) -> str:
    """A company that went through Checkout once: its customer id is known."""
    harness.store.accounts[harness.company.id] = AccountView(
        harness.company.id, "cus_acme", None, None, None
    )
    return "cus_acme"


def test_checkout_completed_upgrades_free_to_starter(harness: Harness, customer: str) -> None:
    harness.gateway.subscriptions[customer] = [subscription("sub_1", "active")]
    response = harness.webhook("checkout.session.completed", customer)
    assert response.status_code == 200
    assert response.json() == {"received": True, "synced": True}
    plan, sub_id, status, period_end = harness.store.snapshot(harness.company.id)
    assert (plan, sub_id, status) == (CompanyPlan.STARTER, "sub_1", "active")
    assert period_end is not None


def test_annual_team_price_maps_to_team(harness: Harness, customer: str) -> None:
    harness.gateway.subscriptions[customer] = [subscription("sub_1", "active", "price_team_y")]
    assert harness.webhook("customer.subscription.created", customer).status_code == 200
    assert harness.store.plans[harness.company.id] is CompanyPlan.TEAM


@pytest.mark.parametrize(
    "event_type",
    [
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.payment_succeeded",
        "invoice.payment_failed",
    ],
)
def test_replaying_any_event_twice_leaves_the_same_state(
    harness: Harness, customer: str, event_type: str
) -> None:
    harness.gateway.subscriptions[customer] = [subscription("sub_1", "active", "price_team_m")]
    assert harness.webhook(event_type, customer).status_code == 200
    first = harness.store.snapshot(harness.company.id)
    assert harness.webhook(event_type, customer).status_code == 200
    assert harness.store.snapshot(harness.company.id) == first
    assert first[0] is CompanyPlan.TEAM


def test_out_of_order_delivery_converges_on_stripe_state(harness: Harness, customer: str) -> None:
    """The deleted event arriving before a stale updated one changes nothing:
    both read the same subscription list."""
    harness.gateway.subscriptions[customer] = [subscription("sub_1", "canceled")]
    harness.webhook("customer.subscription.deleted", customer)
    harness.webhook("customer.subscription.updated", customer)
    assert harness.store.snapshot(harness.company.id) == (CompanyPlan.FREE, None, "canceled", None)


def test_subscription_deleted_drops_to_free(harness: Harness, customer: str) -> None:
    harness.gateway.subscriptions[customer] = [subscription("sub_1", "active")]
    harness.webhook("customer.subscription.created", customer)
    harness.gateway.subscriptions[customer] = [subscription("sub_1", "canceled")]
    assert harness.webhook("customer.subscription.deleted", customer).status_code == 200
    assert harness.store.plans[harness.company.id] is CompanyPlan.FREE


def test_past_due_keeps_the_paid_plan(harness: Harness, customer: str) -> None:
    harness.gateway.subscriptions[customer] = [subscription("sub_1", "past_due", "price_team_m")]
    assert harness.webhook("invoice.payment_failed", customer).status_code == 200
    plan, _sub, status, _end = harness.store.snapshot(harness.company.id)
    assert (plan, status) == (CompanyPlan.TEAM, "past_due")


def test_a_canceled_old_subscription_beside_a_live_one_is_fine(
    harness: Harness, customer: str
) -> None:
    harness.gateway.subscriptions[customer] = [
        subscription("sub_old", "canceled", created=1),
        subscription("sub_new", "active", "price_team_m", created=2),
    ]
    assert harness.webhook("customer.subscription.created", customer).status_code == 200
    assert harness.store.snapshot(harness.company.id)[:2] == (CompanyPlan.TEAM, "sub_new")


def test_two_live_subscriptions_answer_500_and_log(
    harness: Harness, customer: str, caplog: pytest.LogCaptureFixture
) -> None:
    harness.gateway.subscriptions[customer] = [
        subscription("sub_1", "active"),
        subscription("sub_2", "trialing", "price_team_m"),
    ]
    with caplog.at_level(logging.ERROR, logger="ganek_ee.billing.api"):
        response = harness.webhook("customer.subscription.created", customer)
    assert response.status_code == 500
    assert "more than one live subscription: sub_1, sub_2" in caplog.text
    assert harness.company.id not in harness.store.plans


def test_a_price_we_do_not_know_answers_500(harness: Harness, customer: str) -> None:
    harness.gateway.subscriptions[customer] = [subscription("sub_1", "active", "price_other")]
    assert harness.webhook("customer.subscription.created", customer).status_code == 500
    assert harness.company.id not in harness.store.plans


def test_a_failed_db_write_answers_500_so_stripe_retries(harness: Harness, customer: str) -> None:
    harness.gateway.subscriptions[customer] = [subscription("sub_1", "active")]
    harness.store.fail_writes = True
    assert harness.webhook("checkout.session.completed", customer).status_code == 500
    harness.store.fail_writes = False
    assert harness.webhook("checkout.session.completed", customer).status_code == 200
    assert harness.store.plans[harness.company.id] is CompanyPlan.STARTER


def test_ignored_event_types_answer_200_without_a_sync(harness: Harness, customer: str) -> None:
    response = harness.webhook("customer.created", customer)
    assert response.status_code == 200
    assert response.json() == {"received": True, "synced": False}
    assert harness.gateway.list_calls == 0


def test_an_unknown_customer_answers_200(harness: Harness, customer: str) -> None:
    response = harness.webhook("customer.subscription.updated", "cus_someone_else")
    assert response.status_code == 200
    assert response.json()["synced"] is False
    assert harness.gateway.list_calls == 0


def test_a_wrong_signature_is_400(harness: Harness, customer: str) -> None:
    response = harness.webhook("checkout.session.completed", customer, secret="whsec_wrong")  # noqa: S106
    assert response.status_code == 400
    assert harness.gateway.list_calls == 0


def test_an_unsigned_request_is_400(harness: Harness) -> None:
    response = harness.client.post(
        "/api/v1/billing/webhook", content=b'{"type": "checkout.session.completed"}'
    )
    assert response.status_code == 400
