"""Shared API-test helpers."""

from typing import Any

import httpx

PDF_BYTES = b"%PDF-1.4 test cv"


async def upload_pdf(ticket: dict[str, Any], data: bytes = PDF_BYTES) -> httpx.Response:
    """Complete a CV upload ticket the way the browser does: presigned POST,
    policy fields first, the file last."""
    async with httpx.AsyncClient() as raw:
        return await raw.post(
            ticket["upload_url"],
            data=ticket["upload_fields"],
            files={"file": ("cv.pdf", data, ticket["content_type"])},
        )
