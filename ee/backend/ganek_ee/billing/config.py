"""Stripe settings for the hosted plane (card B1c). Read from the
environment only: the core's settings never learn about Stripe.

Prices live in Stripe; the repo only knows their ids (Q4), so the amounts
shown at checkout are whatever the operator configured in the dashboard.
"""

import os
from dataclasses import dataclass
from enum import StrEnum

from app.models.company import CompanyPlan


class Interval(StrEnum):
    MONTH = "month"
    YEAR = "year"


# (plan, interval) -> env var holding the Stripe Price id
PRICE_ENV: dict[tuple[CompanyPlan, Interval], str] = {
    (CompanyPlan.STARTER, Interval.MONTH): "STRIPE_PRICE_STARTER_MONTHLY",
    (CompanyPlan.STARTER, Interval.YEAR): "STRIPE_PRICE_STARTER_ANNUAL",
    (CompanyPlan.TEAM, Interval.MONTH): "STRIPE_PRICE_TEAM_MONTHLY",
    (CompanyPlan.TEAM, Interval.YEAR): "STRIPE_PRICE_TEAM_ANNUAL",
}
SECRET_KEY_ENV = "STRIPE_SECRET_KEY"  # noqa: S105 - an env var name
WEBHOOK_SECRET_ENV = "STRIPE_WEBHOOK_SECRET"  # noqa: S105 - an env var name


@dataclass(frozen=True)
class StripeConfig:
    secret_key: str
    webhook_secret: str
    prices: dict[tuple[CompanyPlan, Interval], str]

    def price_id(self, plan: CompanyPlan, interval: Interval) -> str:
        return self.prices[(plan, interval)]

    def plan_for_price(self, price_id: str) -> CompanyPlan | None:
        for (plan, _interval), configured in self.prices.items():
            if configured == price_id:
                return plan
        return None


def stripe_config_from_env() -> StripeConfig | None:
    """None unless the key, the webhook secret and all four Price ids are
    set: billing is either fully configured or off, never half on."""
    secret = os.environ.get(SECRET_KEY_ENV, "").strip()
    webhook = os.environ.get(WEBHOOK_SECRET_ENV, "").strip()
    prices = {key: os.environ.get(env, "").strip() for key, env in PRICE_ENV.items()}
    if not secret or not webhook or not all(prices.values()):
        return None
    return StripeConfig(secret_key=secret, webhook_secret=webhook, prices=prices)
