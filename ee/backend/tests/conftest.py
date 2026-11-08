"""Shared doubles for the billing tests (card B1c). No database and no
network: the Stripe client and the billing store are swapped through the
routes' dependencies, and webhook payloads are signed with a test secret
exactly as Stripe signs them."""

import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.tenancy import get_staff_company, require_admin
from app.models.company import Company, CompanyPlan
from ganek_ee.billing import api
from ganek_ee.billing.config import PRICE_ENV, SECRET_KEY_ENV, WEBHOOK_SECRET_ENV
from ganek_ee.billing.gateway import SubscriptionView
from ganek_ee.billing.store import AccountView
from ganek_ee.billing.sync import BillingState

WEBHOOK_SECRET = "whsec_test_secret"  # noqa: S105 - test value
PRICES = {
    "STRIPE_PRICE_STARTER_MONTHLY": "price_starter_m",
    "STRIPE_PRICE_STARTER_ANNUAL": "price_starter_y",
    "STRIPE_PRICE_TEAM_MONTHLY": "price_team_m",
    "STRIPE_PRICE_TEAM_ANNUAL": "price_team_y",
}
assert set(PRICES) == set(PRICE_ENV.values())


@pytest.fixture
def stripe_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SECRET_KEY_ENV, "sk_test_not_used")
    monkeypatch.setenv(WEBHOOK_SECRET_ENV, WEBHOOK_SECRET)
    for env, value in PRICES.items():
        monkeypatch.setenv(env, value)


def subscription(
    sub_id: str, status: str, price: str = "price_starter_m", created: int = 1
) -> SubscriptionView:
    return SubscriptionView(
        id=sub_id,
        status=status,
        price_ids=(price,),
        current_period_end=datetime(2026, 12, 8, tzinfo=UTC),
        created=created,
    )


@dataclass
class FakeGateway:
    subscriptions: dict[str, list[SubscriptionView]] = field(default_factory=dict)
    customers_created: list[dict[str, str]] = field(default_factory=list)
    checkouts: list[dict[str, str]] = field(default_factory=list)
    portals: list[dict[str, str]] = field(default_factory=list)
    list_calls: int = 0

    def create_customer(self, *, company_id: str, name: str, email: str) -> str:
        self.customers_created.append({"company_id": company_id, "name": name, "email": email})
        return f"cus_{len(self.customers_created)}"

    def create_checkout_session(self, **kwargs: str) -> str:
        self.checkouts.append(kwargs)
        return "https://checkout.stripe.test/session"

    def create_portal_session(self, **kwargs: str) -> str:
        self.portals.append(kwargs)
        return "https://billing.stripe.test/portal"

    def list_subscriptions(self, customer_id: str) -> list[SubscriptionView]:
        self.list_calls += 1
        return list(self.subscriptions.get(customer_id, []))


class MemoryStore:
    """The SQL store's four operations over dicts, plus the plan written."""

    def __init__(self) -> None:
        self.accounts: dict[uuid.UUID, AccountView] = {}
        self.plans: dict[uuid.UUID, CompanyPlan] = {}
        self.fail_writes = False

    async def account(self, company_id: uuid.UUID) -> AccountView | None:
        return self.accounts.get(company_id)

    async def save_customer(self, company_id: uuid.UUID, customer_id: str) -> None:
        current = self.accounts.setdefault(
            company_id, AccountView(company_id, None, None, None, None)
        )
        current.stripe_customer_id = customer_id

    async def company_for_customer(self, customer_id: str) -> uuid.UUID | None:
        for account in self.accounts.values():
            if account.stripe_customer_id == customer_id:
                return account.company_id
        return None

    async def apply(self, company_id: uuid.UUID, state: BillingState) -> None:
        if self.fail_writes:
            raise RuntimeError("database unavailable")
        account = self.accounts[company_id]
        account.stripe_subscription_id = state.subscription_id
        account.status = state.status
        account.current_period_end = state.current_period_end
        self.plans[company_id] = state.plan

    def snapshot(self, company_id: uuid.UUID) -> tuple[Any, ...]:
        account = self.accounts[company_id]
        return (
            self.plans.get(company_id),
            account.stripe_subscription_id,
            account.status,
            account.current_period_end,
        )


@dataclass
class Harness:
    client: TestClient
    gateway: FakeGateway
    store: MemoryStore
    company: Company
    admin: SimpleNamespace

    def webhook(
        self, event_type: str, customer: str | None, *, secret: str = WEBHOOK_SECRET
    ) -> Any:
        payload = json.dumps(
            {
                "id": f"evt_{uuid.uuid4().hex[:12]}",
                "type": event_type,
                "data": {"object": {"object": "event_object", "customer": customer}},
            }
        )
        # Stripe's v1 scheme, computed by hand: HMAC-SHA256 of "<t>.<body>"
        timestamp = int(time.time())
        signed = f"{timestamp}.{payload}".encode()
        signature = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        return self.client.post(
            "/api/v1/billing/webhook",
            content=payload,
            headers={
                "stripe-signature": f"t={timestamp},v1={signature}",
                "content-type": "application/json",
            },
        )


@pytest.fixture
def harness(stripe_env: None) -> Iterator[Harness]:
    gateway = FakeGateway()
    store = MemoryStore()
    company = Company(id=uuid.uuid4(), slug="acme", name="Acme", plan=CompanyPlan.FREE)
    admin = SimpleNamespace(id=uuid.uuid4(), email="admin@acme.test")
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    app.dependency_overrides[api.get_gateway] = lambda: gateway
    app.dependency_overrides[api.get_store] = lambda: store
    app.dependency_overrides[get_staff_company] = lambda: company
    app.dependency_overrides[require_admin] = lambda: admin
    with TestClient(app) as client:
        yield Harness(client, gateway, store, company, admin)
