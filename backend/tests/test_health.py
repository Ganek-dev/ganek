from httpx import AsyncClient


async def test_health_returns_ok(client: AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["mode"] in {"single", "multi"}


async def test_health_defaults_to_single_mode(client: AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.json()["mode"] == "single"
