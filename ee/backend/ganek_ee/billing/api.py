"""Billing routes (card B1c), mounted under /api/v1 by HostedPolicy.routers()
only when Stripe is fully configured.

- ``GET /billing``: the admin's billing summary for the settings page.
- ``POST /billing/checkout``: a Stripe Checkout session for Starter or Team.
- ``POST /billing/portal``: a Stripe customer portal session (plan changes,
  card, invoices and cancel all live there, not in our UI).
- ``POST /billing/webhook``: Stripe's callback, signature-verified, then the
  convergent sync by customer (R1).

Only the company admin reaches the first three (Q14).
"""

import json
import logging
from datetime import datetime
from typing import Annotated, Any, Literal

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.deps import AdminUser, DbSession, StaffCompany
from app.core import urls
from app.models.company import CompanyPlan
from ganek_ee.billing.config import Interval, StripeConfig, stripe_config_from_env
from ganek_ee.billing.gateway import LiveStripeGateway, StripeGateway
from ganek_ee.billing.store import BillingStore, SqlBillingStore
from ganek_ee.billing.sync import LIVE_STATUSES, SyncError, resolve_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])

# R1: every one of these reduces to "re-sync this customer"; anything else = 200
ACCEPTED_EVENTS = frozenset(
    {
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.payment_succeeded",
        "invoice.payment_failed",
    }
)
SIGNATURE_TOLERANCE_SECONDS = 300


def get_config() -> StripeConfig:
    config = stripe_config_from_env()
    if config is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Billing is not configured")
    return config


Config = Annotated[StripeConfig, Depends(get_config)]


def get_gateway(config: Config) -> StripeGateway:
    return LiveStripeGateway(config.secret_key)


def get_store(db: DbSession) -> BillingStore:
    return SqlBillingStore(db)


Gateway = Annotated[StripeGateway, Depends(get_gateway)]
Store = Annotated[BillingStore, Depends(get_store)]


class BillingOut(BaseModel):
    plan: str
    status: str | None
    current_period_end: datetime | None
    # a Stripe customer exists, so the portal can open
    can_manage: bool


class CheckoutIn(BaseModel):
    plan: Literal["starter", "team"]
    interval: Interval = Interval.MONTH


class RedirectOut(BaseModel):
    url: str


@router.get("", response_model=BillingOut)
async def get_billing(company: StaffCompany, _admin: AdminUser, store: Store) -> BillingOut:
    account = await store.account(company.id)
    return BillingOut(
        plan=company.plan.value,
        status=account.status if account else None,
        current_period_end=account.current_period_end if account else None,
        can_manage=bool(account and account.stripe_customer_id),
    )


@router.post("/checkout", response_model=RedirectOut)
async def create_checkout(
    body: CheckoutIn,
    company: StaffCompany,
    admin: AdminUser,
    config: Config,
    gateway: Gateway,
    store: Store,
) -> RedirectOut:
    account = await store.account(company.id)
    if account and account.stripe_subscription_id and account.status in LIVE_STATUSES:
        # a second Checkout would open a second live subscription (R1 = 500)
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This company already has a subscription. Change the plan in the billing portal.",
        )
    customer_id = account.stripe_customer_id if account else None
    if not customer_id:
        customer_id = await run_in_threadpool(
            lambda: gateway.create_customer(
                company_id=str(company.id), name=company.name, email=admin.email
            )
        )
        await store.save_customer(company.id, customer_id)
    billing_url = urls.admin_billing_url(company)
    price_id = config.price_id(CompanyPlan(body.plan), body.interval)
    url = await run_in_threadpool(
        lambda: gateway.create_checkout_session(
            customer_id=customer_id,
            price_id=price_id,
            company_id=str(company.id),
            success_url=f"{billing_url}?checkout=success",
            cancel_url=billing_url,
        )
    )
    return RedirectOut(url=url)


@router.post("/portal", response_model=RedirectOut)
async def create_portal(
    company: StaffCompany, _admin: AdminUser, gateway: Gateway, store: Store
) -> RedirectOut:
    account = await store.account(company.id)
    if account is None or not account.stripe_customer_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "No billing account yet. Choose a plan first."
        )
    customer_id = account.stripe_customer_id
    url = await run_in_threadpool(
        lambda: gateway.create_portal_session(
            customer_id=customer_id, return_url=urls.admin_billing_url(company)
        )
    )
    return RedirectOut(url=url)


def _customer_id(event: dict[str, Any]) -> str | None:
    obj = (event.get("data") or {}).get("object") or {}
    customer = obj.get("customer")
    if isinstance(customer, dict):  # expanded
        customer = customer.get("id")
    return customer if isinstance(customer, str) and customer else None


@router.post("/webhook")
async def stripe_webhook(
    request: Request, config: Config, gateway: Gateway, store: Store
) -> JSONResponse:
    payload = (await request.body()).decode("utf-8", errors="replace")
    signature = request.headers.get("stripe-signature", "")
    try:
        stripe.WebhookSignature.verify_header(
            payload, signature, config.webhook_secret, SIGNATURE_TOLERANCE_SECONDS
        )
        event = json.loads(payload)
    except (stripe.SignatureVerificationError, ValueError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Stripe signature") from None

    event_type = str(event.get("type", ""))
    customer_id = _customer_id(event)
    if event_type not in ACCEPTED_EVENTS or customer_id is None:
        return JSONResponse({"received": True, "synced": False})
    company_id = await store.company_for_customer(customer_id)
    if company_id is None:
        # not one of ours (or created outside Checkout): a retry cannot help
        logger.warning("stripe webhook %s for unknown customer %s", event_type, customer_id)
        return JSONResponse({"received": True, "synced": False})

    try:
        subscriptions = await run_in_threadpool(lambda: gateway.list_subscriptions(customer_id))
        state = resolve_state(config, subscriptions)
        await store.apply(company_id, state)
    except SyncError as exc:
        logger.error("stripe sync for customer %s refused: %s", customer_id, exc)
        return JSONResponse({"received": True, "synced": False}, status_code=500)
    except Exception:
        # Stripe unreachable or the DB write failed: non-2xx, Stripe retries
        logger.exception("stripe sync for customer %s failed", customer_id)
        return JSONResponse({"received": True, "synced": False}, status_code=500)
    logger.info(
        "stripe sync: company %s plan=%s status=%s", company_id, state.plan.value, state.status
    )
    return JSONResponse({"received": True, "synced": True})
