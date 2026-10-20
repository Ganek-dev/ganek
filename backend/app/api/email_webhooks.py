"""Inbound bounce and complaint events from the email provider (card A7).

One route per provider format. Authentication is HTTP Basic with
``GANEK_EMAIL_WEBHOOK_SECRET`` as the password (the user part is free):
every provider can call ``https://ganek:<secret>@host/api/v1/email/
webhooks/<provider>`` without custom headers. Unset secret means the
feature is off and every call is 401.
"""

import base64
import secrets
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import DbSession
from app.core.config import settings
from app.core.ratelimit import rate_limit
from app.services import suppression

router = APIRouter(prefix="/email/webhooks", tags=["email-webhooks"])

_CHALLENGE = {"WWW-Authenticate": 'Basic realm="ganek-email-webhooks"'}


def _require_secret(request: Request) -> None:
    expected = settings.email_webhook_secret
    header = request.headers.get("authorization", "")
    scheme, _, encoded = header.partition(" ")
    presented: str | None = None
    if scheme.lower() == "basic" and encoded:
        try:
            decoded = base64.b64decode(encoded.strip(), validate=True).decode()
        except (ValueError, UnicodeDecodeError):
            decoded = ""
        _, _, presented = decoded.partition(":")
    # compare against a dummy when unset so timing is uniform either way
    ok = secrets.compare_digest(presented or "", expected or "")
    if not expected or presented is None or not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Webhook secret missing or wrong",
            headers=_CHALLENGE,
        )


@router.post(
    "/mailjet",
    dependencies=[rate_limit("public", lambda: settings.rate_limit_public_per_minute)],
)
async def mailjet_events(request: Request, db: DbSession) -> dict[str, int]:
    """Mailjet Event API callback (bounce, spam, blocked, unsub)."""
    _require_secret(request)
    try:
        payload: Any = await request.json()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Body must be JSON"
        ) from None
    events = suppression.parse_mailjet(payload)
    handled, suppressed = await suppression.apply_events(db, events, source="mailjet")
    return {"received": handled, "suppressed": suppressed}
