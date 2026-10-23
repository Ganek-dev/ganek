import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import AdminUser, CurrentCompany, DbSession
from app.schemas.webhooks import (
    DeliveryOut,
    WebhookEndpointCreate,
    WebhookEndpointCreated,
    WebhookEndpointOut,
)
from app.services import webhooks as webhooks_service

# admin + session only, like API keys: integrations cannot reconfigure themselves
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")


@router.get("", response_model=list[WebhookEndpointOut])
async def list_webhooks(
    db: DbSession, company: CurrentCompany, _admin: AdminUser
) -> list[WebhookEndpointOut]:
    return [
        WebhookEndpointOut(
            **WebhookEndpointOut.model_validate(endpoint).model_dump(exclude={"last_delivery"}),
            last_delivery=DeliveryOut.model_validate(last) if last is not None else None,
        )
        for endpoint, last in await webhooks_service.list_endpoints(db, company)
    ]


@router.post("", response_model=WebhookEndpointCreated, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    payload: WebhookEndpointCreate, db: DbSession, company: CurrentCompany, admin: AdminUser
) -> WebhookEndpointCreated:
    endpoint, secret = await webhooks_service.create_endpoint(
        db, company, name=payload.name, url=payload.url, events=list(payload.events), actor=admin
    )
    return WebhookEndpointCreated(
        **WebhookEndpointOut.model_validate(endpoint).model_dump(), secret=secret
    )


@router.delete("/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    endpoint_id: uuid.UUID, db: DbSession, company: CurrentCompany, admin: AdminUser
) -> None:
    if not await webhooks_service.delete_endpoint(db, company, endpoint_id, actor=admin):
        raise _not_found()


@router.post(
    "/{endpoint_id}/test", response_model=DeliveryOut, status_code=status.HTTP_202_ACCEPTED
)
async def test_webhook(
    endpoint_id: uuid.UUID, db: DbSession, company: CurrentCompany, _admin: AdminUser
) -> DeliveryOut:
    delivery = await webhooks_service.queue_test(db, company, endpoint_id)
    if delivery is None:
        raise _not_found()
    return DeliveryOut.model_validate(delivery)


@router.get("/{endpoint_id}/deliveries", response_model=list[DeliveryOut])
async def list_webhook_deliveries(
    endpoint_id: uuid.UUID, db: DbSession, company: CurrentCompany, _admin: AdminUser
) -> list[DeliveryOut]:
    rows = await webhooks_service.list_deliveries(db, company, endpoint_id)
    if rows is None:
        raise _not_found()
    return [DeliveryOut.model_validate(row) for row in rows]
