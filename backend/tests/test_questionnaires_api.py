from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _register(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": f"Qn Co {uuid4().hex[:6]}",
            "email": f"admin-{uuid4().hex[:8]}@vetd-ci.dev",
            "password": "a-long-secure-password",
        },
    )
    assert resp.status_code == 201, resp.text


def _payload(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "name": "Frontend basics v2",
        "description": "12-question sweep across HTML, CSS and React.",
        "shuffle": False,
        "question_refs": ["py-gil-1", "js-closure-3", "css-box-2"],
    }
    body.update(overrides)
    return body


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_questionnaire_crud_lifecycle(client: AsyncClient) -> None:
    await _register(client)

    created = await client.post("/api/v1/questionnaires", json=_payload())
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Frontend basics v2"
    assert body["shuffle"] is False
    assert body["question_refs"] == ["py-gil-1", "js-closure-3", "css-box-2"]

    listed = await client.get("/api/v1/questionnaires")
    assert [q["id"] for q in listed.json()] == [body["id"]]

    fetched = await client.get(f"/api/v1/questionnaires/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["description"].startswith("12-question")

    patched = await client.patch(
        f"/api/v1/questionnaires/{body['id']}",
        json={"shuffle": True, "question_refs": ["py-gil-1", "new-q-4"]},
    )
    assert patched.status_code == 200
    assert patched.json()["shuffle"] is True
    assert patched.json()["question_refs"] == ["py-gil-1", "new-q-4"]

    deleted = await client.delete(f"/api/v1/questionnaires/{body['id']}")
    assert deleted.status_code == 204
    assert (await client.get(f"/api/v1/questionnaires/{body['id']}")).status_code == 404


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_question_refs_are_deduped_preserving_order(client: AsyncClient) -> None:
    await _register(client)
    resp = await client.post(
        "/api/v1/questionnaires",
        json=_payload(question_refs=["a", "b", "a", "c", "b"]),
    )
    assert resp.status_code == 201
    assert resp.json()["question_refs"] == ["a", "b", "c"]


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_duplicate_name_returns_409(client: AsyncClient) -> None:
    await _register(client)
    assert (await client.post("/api/v1/questionnaires", json=_payload())).status_code == 201
    dup = await client.post("/api/v1/questionnaires", json=_payload())
    assert dup.status_code == 409
    assert "already exists" in dup.json()["detail"]


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_validation_rejects_empty_name_and_oversized_refs(client: AsyncClient) -> None:
    await _register(client)
    empty = await client.post("/api/v1/questionnaires", json=_payload(name=""))
    assert empty.status_code == 422

    too_long = await client.post(
        "/api/v1/questionnaires",
        json=_payload(name="Long refs", question_refs=[f"ref-{i}" for i in range(201)]),
    )
    assert too_long.status_code == 422


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_questionnaires_require_auth(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/questionnaires")).status_code == 401
    assert (await client.post("/api/v1/questionnaires", json=_payload())).status_code == 401


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_tenant_isolation(client: AsyncClient) -> None:
    await _register(client)
    created = (await client.post("/api/v1/questionnaires", json=_payload())).json()

    await client.post("/api/v1/auth/logout")
    await _register(client)
    assert (await client.get(f"/api/v1/questionnaires/{created['id']}")).status_code == 404
    assert (
        await client.patch(f"/api/v1/questionnaires/{created['id']}", json={"name": "X"})
    ).status_code == 404
    assert (await client.get("/api/v1/questionnaires")).json() == []
