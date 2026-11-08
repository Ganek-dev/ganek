"""The thin Stripe client (Q19): the only module that talks to Stripe. Tests
swap it for a fake through the ``get_gateway`` dependency, so CI never
touches the network."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import stripe


@dataclass(frozen=True)
class SubscriptionView:
    """The fields the sync needs from one Stripe subscription."""

    id: str
    status: str
    price_ids: tuple[str, ...]
    current_period_end: datetime | None
    created: int = 0


class StripeGateway(Protocol):
    def create_customer(self, *, company_id: str, name: str, email: str) -> str: ...

    def create_checkout_session(
        self, *, customer_id: str, price_id: str, company_id: str, success_url: str, cancel_url: str
    ) -> str: ...

    def create_portal_session(self, *, customer_id: str, return_url: str) -> str: ...

    def list_subscriptions(self, customer_id: str) -> list[SubscriptionView]: ...


def _ts(value: Any) -> datetime | None:
    return datetime.fromtimestamp(int(value), tz=UTC) if value else None


def subscription_view(sub: Any) -> SubscriptionView:
    """``sub`` = a Stripe subscription (StripeObject or plain dict). Newer API
    versions carry ``current_period_end`` on the items, older ones on the
    subscription; take whichever is there."""
    items = (sub.get("items") or {}).get("data") or []
    price_ids = tuple(str(item["price"]["id"]) for item in items if item.get("price"))
    period_end = sub.get("current_period_end")
    if period_end is None and items:
        period_end = items[0].get("current_period_end")
    return SubscriptionView(
        id=str(sub["id"]),
        status=str(sub["status"]),
        price_ids=price_ids,
        current_period_end=_ts(period_end),
        created=int(sub.get("created") or 0),
    )


class LiveStripeGateway:
    def __init__(self, secret_key: str) -> None:
        self._client = stripe.StripeClient(secret_key)

    def create_customer(self, *, company_id: str, name: str, email: str) -> str:
        customer = self._client.v1.customers.create(
            params={"name": name, "email": email, "metadata": {"company_id": company_id}}
        )
        return str(customer.id)

    def create_checkout_session(
        self, *, customer_id: str, price_id: str, company_id: str, success_url: str, cancel_url: str
    ) -> str:
        session = self._client.v1.checkout.sessions.create(
            params={
                "mode": "subscription",
                "customer": customer_id,
                "client_reference_id": company_id,
                "line_items": [{"price": price_id, "quantity": 1}],
                # Stripe Tax from day one (decisions/2026-11-08-stripe-tax-amends-bm4)
                "automatic_tax": {"enabled": True},
                "tax_id_collection": {"enabled": True},
                # tax needs the address; an existing customer must allow updates
                "customer_update": {"address": "auto", "name": "auto"},
                "success_url": success_url,
                "cancel_url": cancel_url,
            }
        )
        return str(session.url)

    def create_portal_session(self, *, customer_id: str, return_url: str) -> str:
        session = self._client.v1.billing_portal.sessions.create(
            params={"customer": customer_id, "return_url": return_url}
        )
        return str(session.url)

    def list_subscriptions(self, customer_id: str) -> list[SubscriptionView]:
        page = self._client.v1.subscriptions.list(
            params={"customer": customer_id, "status": "all", "limit": 100}
        )
        return [subscription_view(sub) for sub in page.auto_paging_iter()]
