"""Convergent subscription sync (R1, card B1c). Every accepted webhook event
reduces to one customer id; the customer's subscriptions are listed from
Stripe and the result is written. Nothing depends on the event's own
payload or order, so replays and out-of-order deliveries converge on the
same state (no event log table, Q11)."""

from dataclasses import dataclass
from datetime import datetime

from app.models.company import CompanyPlan
from ganek_ee.billing.config import StripeConfig
from ganek_ee.billing.gateway import SubscriptionView

# R1: a subscription in one of these is paid for (past_due keeps the plan
# while Stripe retries the card, Q16)
LIVE_STATUSES = frozenset({"active", "trialing", "past_due"})


class SyncError(Exception):
    """The webhook answers 500 so Stripe retries once the cause is fixed."""


class TwoLiveSubscriptions(SyncError):
    pass


class UnknownPrice(SyncError):
    pass


@dataclass(frozen=True)
class BillingState:
    plan: CompanyPlan
    subscription_id: str | None
    status: str | None
    current_period_end: datetime | None


def resolve_state(config: StripeConfig, subscriptions: list[SubscriptionView]) -> BillingState:
    live = [sub for sub in subscriptions if sub.status in LIVE_STATUSES]
    if len(live) > 1:
        ids = ", ".join(sorted(sub.id for sub in live))
        raise TwoLiveSubscriptions(f"more than one live subscription: {ids}")
    if not live:
        # deleted (or never paid): back to Free, nothing closed (Q8, Q16)
        latest = max(subscriptions, key=lambda sub: sub.created, default=None)
        return BillingState(
            plan=CompanyPlan.FREE,
            subscription_id=None,
            status=latest.status if latest else None,
            current_period_end=None,
        )
    sub = live[0]
    plans = {config.plan_for_price(price) for price in sub.price_ids}
    plans.discard(None)
    if len(plans) != 1:
        raise UnknownPrice(f"subscription {sub.id} prices {sub.price_ids} match no single plan")
    plan = plans.pop()
    assert plan is not None
    return BillingState(
        plan=plan,
        subscription_id=sub.id,
        status=sub.status,
        current_period_end=sub.current_period_end,
    )
