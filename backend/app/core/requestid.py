"""Request id middleware (pure ASGI so the id is still set while uvicorn
writes the access line, which happens inside send()).

An inbound X-Request-ID is honoured when it looks like an id (so a reverse
proxy or the frontend can correlate); anything else gets a fresh uuid.
The id is echoed as the X-Request-ID response header and stamped on every
log record of the request via app.core.logcfg.request_id_var.
"""

import re
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders

from app.core import observability
from app.core.logcfg import request_id_var

HEADER = "x-request-id"
_VALID = re.compile(r"[A-Za-z0-9._-]{1,64}")

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def resolve_request_id(inbound: str | None) -> str:
    if inbound and _VALID.fullmatch(inbound):
        return inbound
    return uuid4().hex


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = resolve_request_id(Headers(scope=scope).get(HEADER))
        scope["request_id"] = request_id

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        token = request_id_var.set(request_id)
        observability.tag_request(request_id)
        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_var.reset(token)
