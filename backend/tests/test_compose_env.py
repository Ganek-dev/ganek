"""docker-compose.yml: the worker talks to the same Postgres, Redis and S3 as
the backend. The worker once had no GANEK_S3_ENDPOINT_URL, fell back to
localhost:9000 and failed every nightly purge and demo reset at the first CV
delete."""

from pathlib import Path

import pytest
import yaml

COMPOSE = Path(__file__).resolve().parent.parent.parent / "docker-compose.yml"
SHARED = (
    "GANEK_DATABASE_URL",
    "GANEK_REDIS_URL",
    "GANEK_S3_ENDPOINT_URL",
    "GANEK_S3_PUBLIC_ENDPOINT_URL",
)


@pytest.mark.skipif(not COMPOSE.exists(), reason="runs from a repo checkout only")
def test_worker_shares_backend_service_urls() -> None:
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    backend = services["backend"]["environment"]
    worker = services["worker"]["environment"]
    assert {key: worker.get(key) for key in SHARED} == {key: backend[key] for key in SHARED}
    assert "minio" in services["worker"]["depends_on"]
