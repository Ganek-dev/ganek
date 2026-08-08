"""Object storage for CVs. Presigned PUT uploads, server-side validation.

Presigned URLs are generated against the *public* endpoint (the candidate's
browser uploads directly); head/delete operations use the internal endpoint.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import anyio.to_thread
import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from app.core.config import settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

CV_CONTENT_TYPE = "application/pdf"
UPLOAD_URL_TTL_SECONDS = 600

_BOTO_CONFIG = BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"})


def _make_client(endpoint_url: str) -> "S3Client":
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name="us-east-1",
        config=_BOTO_CONFIG,
    )


@lru_cache(maxsize=1)
def _internal_client() -> "S3Client":
    return _make_client(settings.s3_endpoint_url)


@lru_cache(maxsize=1)
def _public_client() -> "S3Client":
    return _make_client(settings.s3_public_endpoint_url or settings.s3_endpoint_url)


@dataclass(frozen=True)
class ObjectStat:
    size: int
    content_type: str


def ensure_bucket() -> None:
    client = _internal_client()
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    except ClientError:
        client.create_bucket(Bucket=settings.s3_bucket)


def build_cv_key(company_id: UUID) -> str:
    return f"cvs/{company_id}/{uuid4().hex}.pdf"


def presign_cv_upload(object_key: str) -> str:
    return _public_client().generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.s3_bucket,
            "Key": object_key,
            "ContentType": CV_CONTENT_TYPE,
        },
        ExpiresIn=UPLOAD_URL_TTL_SECONDS,
    )


def sanitize_disposition_filename(filename: str) -> str:
    """Strip anything that could break out of the quoted disposition value."""
    cleaned = "".join(c for c in filename if c.isprintable() and c not in '"\\;')
    cleaned = cleaned.strip() or "cv.pdf"
    return cleaned[:150]


def presign_cv_download(object_key: str, filename: str) -> str:
    safe_name = sanitize_disposition_filename(filename)
    return _public_client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": settings.s3_bucket,
            "Key": object_key,
            "ResponseContentDisposition": f'attachment; filename="{safe_name}"',
        },
        ExpiresIn=UPLOAD_URL_TTL_SECONDS,
    )


LOGO_MAX_BYTES = 2 * 1024 * 1024  # matches the branding card copy (max 2 MB)


def build_logo_key(company_id: UUID) -> str:
    """Stable key — replacing a logo overwrites in place; the served URL's
    version query param handles cache busting."""
    return f"logos/{company_id}"


def _put_object(object_key: str, data: bytes, content_type: str) -> None:
    _internal_client().put_object(
        Bucket=settings.s3_bucket, Key=object_key, Body=data, ContentType=content_type
    )


async def put_object(object_key: str, data: bytes, content_type: str) -> None:
    await anyio.to_thread.run_sync(_put_object, object_key, data, content_type)


def _get_object(object_key: str) -> tuple[bytes, str] | None:
    try:
        result = _internal_client().get_object(Bucket=settings.s3_bucket, Key=object_key)
    except ClientError:
        return None
    return result["Body"].read(), result.get("ContentType", "application/octet-stream")


async def get_object(object_key: str) -> tuple[bytes, str] | None:
    return await anyio.to_thread.run_sync(_get_object, object_key)


def _delete_object(object_key: str) -> None:
    _internal_client().delete_object(Bucket=settings.s3_bucket, Key=object_key)


async def delete_object(object_key: str) -> None:
    await anyio.to_thread.run_sync(_delete_object, object_key)


def _stat_object(object_key: str) -> ObjectStat | None:
    try:
        head = _internal_client().head_object(Bucket=settings.s3_bucket, Key=object_key)
    except ClientError:
        return None
    return ObjectStat(size=head["ContentLength"], content_type=head.get("ContentType", ""))


async def stat_object(object_key: str) -> ObjectStat | None:
    return await anyio.to_thread.run_sync(_stat_object, object_key)


async def ensure_bucket_async() -> None:
    await anyio.to_thread.run_sync(ensure_bucket)
