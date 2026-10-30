"""Workspace email templates (card "Candidate emails", PR 3)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EmailTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    name: str
    subject: str
    body: str
    is_default: bool
    created_at: datetime
    updated_at: datetime


class EmailTemplateCreate(BaseModel):
    kind: str = Field(max_length=40)
    name: str = Field(max_length=80)
    subject: str = Field(max_length=200)
    body: str = Field(max_length=20_000)


class EmailTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    subject: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, max_length=20_000)


class EmailKindIn(BaseModel):
    kind: str = Field(max_length=40)


class EmailTemplatePreviewIn(BaseModel):
    kind: str = Field(max_length=40)
    subject: str = Field(max_length=200)
    body: str = Field(max_length=20_000)


class BuiltinTemplateOut(BaseModel):
    subject: str
    body: str


class EmailKindOut(BaseModel):
    kind: str
    label: str
    placeholders: list[str]
    builtin: BuiltinTemplateOut
    templates: list[EmailTemplateOut]


class EmailTemplatesOut(BaseModel):
    kinds: list[EmailKindOut]
