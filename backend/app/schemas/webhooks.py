import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.webhook import DeliveryStatus
from app.services.webhooks import validate_url

WebhookEvent = Literal["application.created", "stage.changed", "quiz.completed"]


class WebhookEndpointCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=12, max_length=500)
    events: list[WebhookEvent] = Field(min_length=1)

    @field_validator("url")
    @classmethod
    def _public_https(cls, value: str) -> str:
        return validate_url(value)  # InvalidUrl is a ValueError -> 422

    @field_validator("events")
    @classmethod
    def _unique(cls, value: list[WebhookEvent]) -> list[WebhookEvent]:
        return list(dict.fromkeys(value))


class DeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event: str
    status: DeliveryStatus
    attempts: int
    last_error: str | None
    response_status: int | None
    created_at: datetime
    delivered_at: datetime | None


class WebhookEndpointOut(BaseModel):
    """Never the secret: it exists only in the create response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    url: str
    events: list[str]
    is_active: bool
    created_at: datetime
    last_delivery: DeliveryOut | None = None


class WebhookEndpointCreated(WebhookEndpointOut):
    secret: str
