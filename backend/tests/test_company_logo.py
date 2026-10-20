"""Branding logo (screen 10, option B): validated upload + same-origin serving."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.db import database_reachable, s3_reachable

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-png-body"
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"fake-jpeg-body"
SVG_BYTES = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>'
EVIL_SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _register(client: AsyncClient) -> str:
    name = f"Logo Co {uuid4().hex[:6]}"
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": name,
            "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
            "password": "a-long-secure-password",
        },
    )
    assert resp.status_code == 201, resp.text
    return name.lower().replace(" ", "-")


async def _upload(client: AsyncClient, data: bytes, content_type: str, name: str = "logo.png"):
    return await client.post("/api/v1/company/logo", files={"file": (name, data, content_type)})


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_upload_serve_replace_and_remove(client: AsyncClient) -> None:
    slug = await _register(client)

    resp = await _upload(client, PNG_BYTES, "image/png")
    assert resp.status_code == 200, resp.text
    logo_url = resp.json()["logo_url"]
    assert logo_url is not None
    assert f"/api/v1/public/companies/{slug}/logo/" in logo_url
    png_path = logo_url.split("/api/v1", 1)[1]

    # content-addressed path: immutable for a year (card A8)
    served = await client.get(f"/api/v1{png_path}")
    assert served.status_code == 200
    assert served.content == PNG_BYTES
    assert served.headers["content-type"] == "image/png"
    assert served.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert "default-src 'none'" in served.headers["content-security-policy"]

    # the pre-A8 mutable path still serves, with the short cache
    served = await client.get(f"/api/v1/public/companies/{slug}/logo")
    assert served.status_code == 200
    assert served.content == PNG_BYTES
    assert served.headers["cache-control"] == "public, max-age=3600"

    # replace with an SVG: same key, new URL; the old digest 404s instead of
    # serving a stale image under an immutable header
    resp = await _upload(client, SVG_BYTES, "image/svg+xml", "logo.svg")
    assert resp.status_code == 200
    svg_url = resp.json()["logo_url"]
    assert svg_url != logo_url
    served = await client.get(f"/api/v1{svg_url.split('/api/v1', 1)[1]}")
    assert served.content == SVG_BYTES
    assert served.headers["content-type"] == "image/svg+xml"
    assert (await client.get(f"/api/v1{png_path}")).status_code == 404

    # remove → cleared and public 404
    resp = await client.delete("/api/v1/company/logo")
    assert resp.status_code == 200
    assert resp.json()["logo_url"] is None
    assert (await client.get(f"/api/v1/public/companies/{slug}/logo")).status_code == 404


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_logo_validation(client: AsyncClient) -> None:
    await _register(client)
    cases = [
        (b"plain text pretending", "image/png", "not an image"),
        (EVIL_SVG, "image/svg+xml", "scriptable svg"),
        (b"\x89PNG\r\n\x1a\n" + b"x" * (2 * 1024 * 1024), "image/png", "over 2 MB"),
        (b"", "image/png", "empty"),
    ]
    for data, content_type, label in cases:
        resp = await _upload(client, data, content_type)
        assert resp.status_code == 422, label
    # JPEG magic sniffing works regardless of the declared type
    resp = await _upload(client, JPEG_BYTES, "application/octet-stream", "logo.bin")
    assert resp.status_code == 200
    assert (
        await client.get(
            f"/api/v1/public/companies/{(await client.get('/api/v1/company')).json()['slug']}/logo"
        )
    ).headers["content-type"] == "image/jpeg"


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_logo_is_admin_only(client: AsyncClient) -> None:
    await _register(client)
    member_email = f"member-{uuid4().hex[:8]}@ganek-ci.dev"
    member_pw = "member-password-1234"
    resp = await client.post(
        "/api/v1/users", json={"email": member_email, "password": member_pw, "role": "member"}
    )
    assert resp.status_code == 201
    await client.post("/api/v1/auth/logout")
    assert (
        await client.post("/api/v1/auth/login", json={"email": member_email, "password": member_pw})
    ).status_code == 200
    assert (await _upload(client, PNG_BYTES, "image/png")).status_code == 403
    assert (await client.delete("/api/v1/company/logo")).status_code == 403


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_missing_logo_is_404(client: AsyncClient) -> None:
    slug = await _register(client)
    assert (await client.get(f"/api/v1/public/companies/{slug}/logo")).status_code == 404
