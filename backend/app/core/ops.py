"""Operator plane gate (board card "Operator plane").

The /ops routes are the one place a request reads across tenants, so the
bypass is explicit: a session whose user id is on GANEK_SUPERADMIN_USER_IDS,
logged on every call. Everyone else, signed in or not, gets the same 404 an
unknown route gets, so the routes do not show up for a tenant probing them.
"""

import logging
import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.core.config import settings
from app.core.security import SESSION_COOKIE_NAME, read_session_token
from app.core.tenancy import DbSession
from app.models import User

logger = logging.getLogger("app.ops")

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


def superadmin_ids() -> frozenset[uuid.UUID]:
    """The allow-list; malformed entries are skipped (and logged), never fatal."""
    ids: set[uuid.UUID] = set()
    for raw in settings.superadmin_user_ids.split(","):
        value = raw.strip()
        if not value:
            continue
        try:
            ids.add(uuid.UUID(value))
        except ValueError:
            logger.warning("ignoring malformed GANEK_SUPERADMIN_USER_IDS entry")
    return frozenset(ids)


async def require_superadmin(request: Request, db: DbSession) -> User:
    allowed = superadmin_ids()
    token = request.cookies.get(SESSION_COOKIE_NAME)
    parsed = read_session_token(token) if token and allowed else None
    if parsed is None or parsed[0] not in allowed:
        raise _NOT_FOUND
    user = await db.get(User, parsed[0])
    if user is None or not user.is_active or user.token_version != parsed[1]:
        raise _NOT_FOUND
    logger.info("ops access user=%s %s %s", user.id, request.method, request.url.path)
    return user


Superadmin = Annotated[User, Depends(require_superadmin)]
