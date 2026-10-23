"""Per-company API keys (card D4, part A): mint, list, revoke, authenticate.

The secret ``gk_<43 url-safe chars>`` is returned exactly once; the row
keeps sha256(secret) and a 12-char prefix for display. Authentication is a
hash lookup; ``last_used_at`` is touched at most once a minute so a busy
integration does not turn every read into a write.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, User
from app.models.api_key import ApiKey, ApiKeyScope
from app.services import activity

KEY_PREFIX = "gk_"
PREFIX_LENGTH = 12
_TOUCH_INTERVAL = timedelta(minutes=1)


class KeyRejected(Exception):
    """Unknown, malformed or revoked key (401 at the edge)."""


class ScopeTooLow(Exception):
    """A read key on a write route (403 at the edge)."""


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def looks_like_key(token: str) -> bool:
    return token.startswith(KEY_PREFIX)


async def create(
    db: AsyncSession, company: Company, *, name: str, scope: ApiKeyScope, actor: User
) -> tuple[ApiKey, str]:
    secret = KEY_PREFIX + secrets.token_urlsafe(32)
    key = ApiKey(
        company_id=company.id,
        name=name,
        prefix=secret[:PREFIX_LENGTH],
        key_hash=_hash(secret),
        scope=scope,
        created_by_user_id=actor.id,
    )
    db.add(key)
    await db.flush()
    activity.record(
        db,
        company_id=company.id,
        type=activity.API_KEY_CREATED,
        actor_user_id=actor.id,
        payload={"name": name, "prefix": key.prefix, "scope": scope.value},
    )
    await db.commit()
    await db.refresh(key)
    return key, secret


async def list_keys(db: AsyncSession, company: Company) -> list[ApiKey]:
    result = await db.execute(
        select(ApiKey).where(ApiKey.company_id == company.id).order_by(ApiKey.created_at.desc())
    )
    return list(result.scalars().all())


async def revoke(db: AsyncSession, company: Company, key_id: uuid.UUID, *, actor: User) -> bool:
    """False when the key is unknown to this tenant or already revoked."""
    key = (
        await db.execute(select(ApiKey).where(ApiKey.id == key_id, ApiKey.company_id == company.id))
    ).scalar_one_or_none()
    if key is None or key.revoked_at is not None:
        return False
    key.revoked_at = datetime.now(UTC)
    activity.record(
        db,
        company_id=company.id,
        type=activity.API_KEY_REVOKED,
        actor_user_id=actor.id,
        payload={"name": key.name, "prefix": key.prefix},
    )
    await db.commit()
    return True


async def authenticate(db: AsyncSession, token: str, *, write: bool = False) -> Company:
    """Resolve a bearer token to its company, or raise. ``write`` demands
    the write scope."""
    if not looks_like_key(token):
        raise KeyRejected
    key = (
        await db.execute(select(ApiKey).where(ApiKey.key_hash == _hash(token)))
    ).scalar_one_or_none()
    if key is None or key.revoked_at is not None:
        raise KeyRejected
    if write and key.scope is not ApiKeyScope.WRITE:
        raise ScopeTooLow
    company = await db.get(Company, key.company_id)
    if company is None:
        raise KeyRejected
    now = datetime.now(UTC)
    if key.last_used_at is None or now - key.last_used_at > _TOUCH_INTERVAL:
        key.last_used_at = now
        await db.commit()
    return company
