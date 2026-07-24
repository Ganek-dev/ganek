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
            "company_name": f"QCo {uuid4().hex[:6]}",
            "email": f"admin-{uuid4().hex[:8]}@vetd-ci.dev",
            "password": "a-long-secure-password",
        },
    )
    assert resp.status_code == 201, resp.text


def _question_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "prompt_md": "What does our internal tool `frobnicator` do?",
        "options": {"a": "Frobnicates", "b": "Compiles", "c": "Deploys", "d": "Nothing"},
        "correct_key": "a",
        "explanation_md": "It frobnicates, obviously.",
        "tags": ["  Frobnication ", "internal"],
        "difficulty": 2,
        "time_limit_seconds": 20,
    }
    payload.update(overrides)
    return payload


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_question_crud_and_retire(client: AsyncClient) -> None:
    await _register(client)

    resp = await client.post("/api/v1/questions", json=_question_payload())
    assert resp.status_code == 201, resp.text
    question = resp.json()
    assert question["id"].startswith("co-")
    assert question["tags"] == ["frobnication", "internal"]  # normalized + sorted
    assert question["status"] == "active"
    assert question["correct_key"] == "a"  # recruiter-facing: allowed

    listed = (await client.get("/api/v1/questions")).json()
    assert [q["id"] for q in listed] == [question["id"]]

    resp = await client.patch(f"/api/v1/questions/{question['id']}", json={"difficulty": 5})
    assert resp.status_code == 200
    assert resp.json()["difficulty"] == 5

    resp = await client.delete(f"/api/v1/questions/{question['id']}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "retired"


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_question_validation(client: AsyncClient) -> None:
    await _register(client)
    bad = _question_payload(options={"a": "One", "b": "Two"})
    assert (await client.post("/api/v1/questions", json=bad)).status_code == 422
    bad = _question_payload(correct_key="e")
    assert (await client.post("/api/v1/questions", json=bad)).status_code == 422
    bad = _question_payload(tags=[])
    assert (await client.post("/api/v1/questions", json=bad)).status_code == 422


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_questions_are_tenant_scoped(client: AsyncClient) -> None:
    await _register(client)
    question = (await client.post("/api/v1/questions", json=_question_payload())).json()

    await client.post("/api/v1/auth/logout")
    await _register(client)
    assert (await client.get("/api/v1/questions")).json() == []
    assert (await client.get(f"/api/v1/questions/{question['id']}")).status_code == 405
    assert (
        await client.patch(f"/api/v1/questions/{question['id']}", json={"difficulty": 4})
    ).status_code == 404
    assert (await client.delete(f"/api/v1/questions/{question['id']}")).status_code == 404
