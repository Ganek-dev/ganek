"""The access boundary: a reviewer session reaches no recruiter route (spec
4.1). API keys stay unrestricted."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.dependencies.models import Dependant
from fastapi.routing import iter_route_contexts
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_invite_token
from app.core.tenancy import (
    get_api_company,
    get_current_user,
    get_read_principal,
    get_write_principal,
)
from app.main import app
from app.models import Job, JobStatus, Scorecard
from app.services import email as email_service
from tests.test_scorecards_api import Co, _company, _login

PW = "a-long-secure-password"
RECRUITER_ONLY = "This action requires a recruiter account"
ADMIN_ONLY = "This action requires an admin account"

# Authenticated routes a reviewer session may reach (spec 4.1). Task 14 adds
# the /review routes here. Everything session-gated and not listed must 403.
REVIEWER_ALLOWED: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/api/v1/auth/me"),
        ("POST", "/api/v1/auth/mfa/enrol"),
        ("POST", "/api/v1/auth/mfa/confirm"),
        ("POST", "/api/v1/auth/mfa/disable"),
        ("POST", "/api/v1/auth/change-password"),
        ("POST", "/api/v1/auth/sign-out-everywhere"),
        ("PATCH", "/api/v1/users/me"),
        ("GET", "/api/v1/users/me/availability"),
        ("PUT", "/api/v1/users/me/availability"),
        ("GET", "/api/v1/users"),
        ("GET", "/api/v1/company/summary"),
        ("GET", "/api/v1/stats/queue"),
        ("POST", "/api/v1/stats/queue/dismiss"),
        ("GET", "/api/v1/scorecards/mine"),
        ("PUT", "/api/v1/scorecards/applications/{application_id}/mine"),
        ("POST", "/api/v1/scorecards/applications/{application_id}/mine/decline"),
    }
)

# Not session-gated at all: public career pages, candidate capability tokens,
# pre-login auth, inbound provider webhooks. Listed route by route so a new
# route cannot slip in unclassified.
NOT_SESSION_GATED: frozenset[tuple[str, str]] = frozenset(
    {
        # pre-login auth
        ("POST", "/api/v1/auth/register"),
        ("POST", "/api/v1/auth/login"),
        ("POST", "/api/v1/auth/mfa"),
        ("GET", "/api/v1/auth/providers"),
        ("POST", "/api/v1/auth/logout"),
        ("POST", "/api/v1/auth/verify-email"),
        ("POST", "/api/v1/auth/resend-verification"),
        ("POST", "/api/v1/auth/forgot-password"),
        ("POST", "/api/v1/auth/reset-password"),
        ("GET", "/api/v1/auth/google/start"),
        ("GET", "/api/v1/auth/google/callback"),
        ("GET", "/api/v1/auth/google/signup/pending"),
        ("POST", "/api/v1/auth/google/signup"),
        # inbound webhooks
        ("POST", "/api/v1/email/webhooks/mailjet"),
        # public career pages
        ("GET", "/api/v1/public/companies/{slug}"),
        ("GET", "/api/v1/public/companies/{slug}/jobs/{job_slug}"),
        ("GET", "/api/v1/public/company"),
        ("GET", "/api/v1/public/company/jobs/{job_slug}"),
        ("GET", "/api/v1/public/companies/{slug}/privacy"),
        ("GET", "/api/v1/public/company/privacy"),
        ("GET", "/api/v1/public/companies/{slug}/jobs-feed"),
        ("GET", "/api/v1/public/challenge"),
        ("GET", "/api/v1/public/companies/{slug}/logo"),
        ("GET", "/api/v1/public/companies/{slug}/logo/{digest}"),
        ("GET", "/api/v1/public/company/jobs-feed"),
        ("POST", "/api/v1/public/companies/{slug}/jobs/{job_slug}/apply/upload-url"),
        ("POST", "/api/v1/public/companies/{slug}/jobs/{job_slug}/apply"),
        ("POST", "/api/v1/public/company/jobs/{job_slug}/apply/upload-url"),
        ("POST", "/api/v1/public/company/jobs/{job_slug}/apply"),
        # candidate and invitee capability tokens
        ("GET", "/api/v1/public/quiz/{token}"),
        ("POST", "/api/v1/public/quiz/{token}/practice"),
        ("POST", "/api/v1/public/quiz/{token}/next"),
        ("POST", "/api/v1/public/quiz/{token}/answer"),
        ("POST", "/api/v1/public/quiz/{token}/events"),
        ("POST", "/api/v1/public/quiz/{token}/request-reissue"),
        ("GET", "/api/v1/public/applications/{token}"),
        ("POST", "/api/v1/public/applications/{token}/withdraw"),
        ("POST", "/api/v1/public/applications/{token}/request-data"),
        ("POST", "/api/v1/public/applications/{token}/request-deletion"),
        ("GET", "/api/v1/public/invites/{token}"),
        ("POST", "/api/v1/public/invites/{token}/accept"),
        ("GET", "/api/v1/public/interviews/{token}"),
        ("GET", "/api/v1/public/interviews/{token}/invite.ics"),
        ("POST", "/api/v1/public/interviews/{token}/book"),
        ("POST", "/api/v1/public/interviews/{token}/reschedule"),
        ("POST", "/api/v1/public/interviews/{token}/cancel"),
    }
)

_SESSION_DEPENDENCIES = {
    get_current_user,
    get_api_company,
    get_read_principal,
    get_write_principal,
}


def _walk_routes() -> dict[tuple[str, str], Dependant]:
    """Every (method, path) under /api/v1. FastAPI keeps included routers
    behind a wrapper in app.routes, so a plain isinstance(APIRoute) walk
    finds nothing and would pass vacuously; test_walk_is_not_vacuous guards it."""
    routes: dict[tuple[str, str], Dependant] = {}
    for context in iter_route_contexts(app.routes):
        path = context.path
        if not path or not path.startswith("/api/v1"):
            continue
        for method in context.methods or ():
            if method not in {"HEAD", "OPTIONS"}:
                routes[(method, path)] = context.original_route.dependant  # type: ignore[attr-defined]
    return routes


def _uses_session(dependant: Dependant) -> bool:
    return dependant.call in _SESSION_DEPENDENCIES or any(
        _uses_session(sub) for sub in dependant.dependencies
    )


def _fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", lambda _: str(uuid4()), path)


@pytest.fixture(autouse=True)
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "mode", "multi")


@dataclass
class Env:
    co: Co
    reviewer: dict[str, str]
    reviewer_id: str


async def _invite_reviewer(client: AsyncClient) -> tuple[dict[str, str], str]:
    """Invite and accept as the spec's flow does; leaves the client signed in
    as the new reviewer."""
    email = f"reviewer-{uuid4().hex[:8]}@ganek-ci.dev"
    invite = await client.post("/api/v1/users/invites", json={"email": email, "role": "reviewer"})
    assert invite.status_code == 201, invite.text
    assert invite.json()["role"] == "reviewer"
    token = create_invite_token(UUID(invite.json()["id"]))
    accepted = await client.post(f"/api/v1/public/invites/{token}/accept", json={"password": PW})
    assert accepted.status_code in (200, 201), accepted.text
    assert accepted.json()["role"] == "reviewer"
    return {"email": email, "password": PW}, accepted.json()["id"]


async def _env(client: AsyncClient, db: AsyncSession) -> Env:
    co = await _company(client, db)
    reviewer, reviewer_id = await _invite_reviewer(client)
    return Env(co, reviewer, reviewer_id)


async def _request_from_admin(client: AsyncClient, env: Env, reviewer_id: str) -> dict[str, Any]:
    await _login(client, env.co.admin)
    resp = await client.post(
        f"/api/v1/scorecards/applications/{env.co.application_id}",
        json={"reviewer_user_id": reviewer_id},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.usefixtures("migrated_db")
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/v1/applications", None),
        ("GET", "/api/v1/applications/{id}", None),
        ("GET", "/api/v1/applications/{id}/timeline", None),
        ("GET", "/api/v1/applications/{id}/notes", None),
        ("GET", "/api/v1/applications/export", None),
        ("PATCH", "/api/v1/applications/{id}/stage", {"stage": "rejected"}),
        ("GET", "/api/v1/jobs", None),
        ("GET", "/api/v1/questions", None),
        ("GET", "/api/v1/questionnaires", None),
        ("GET", "/api/v1/stats/overview", None),
        ("GET", "/api/v1/stats/today", None),
        ("GET", "/api/v1/tasks", None),
        ("GET", "/api/v1/activity", None),
        ("GET", "/api/v1/company/email-templates", None),
        ("GET", "/api/v1/scorecards/applications/{id}", None),
        ("POST", "/api/v1/scorecards/applications/{id}", {"reviewer_user_id": "{member}"}),
        ("POST", "/api/v1/applications/{id}/notes", {"body": "A note"}),
    ],
)
async def test_reviewer_gets_403(
    client: AsyncClient,
    db_session: AsyncSession,
    method: str,
    path: str,
    body: dict[str, str] | None,
) -> None:
    env = await _env(client, db_session)
    if body and body.get("reviewer_user_id"):
        body = {"reviewer_user_id": env.co.member_id}
    resp = await client.request(
        method, path.format(id=env.co.application_id), **({"json": body} if body else {})
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == RECRUITER_ONLY


@pytest.mark.usefixtures("migrated_db")
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/auth/me",
        "/api/v1/company/summary",
        "/api/v1/stats/queue",
        "/api/v1/users",
        "/api/v1/scorecards/mine",
        "/api/v1/users/me/availability",
    ],
)
async def test_reviewer_allowed_routes(
    client: AsyncClient, db_session: AsyncSession, path: str
) -> None:
    await _env(client, db_session)
    resp = await client.get(path)
    assert resp.status_code == 200, resp.text


def test_route_lists_are_honest() -> None:
    routes = _walk_routes()
    assert not REVIEWER_ALLOWED & NOT_SESSION_GATED
    # a renamed route must not leave a stale entry that hides its replacement
    assert not (REVIEWER_ALLOWED | NOT_SESSION_GATED) - routes.keys()
    # the exclusion list holds only routes that really ignore the session
    assert not [key for key in NOT_SESSION_GATED if _uses_session(routes[key])]
    assert not [key for key in REVIEWER_ALLOWED if not _uses_session(routes[key])]


def test_walk_is_not_vacuous() -> None:
    routes = _walk_routes()
    documented = {
        (method.upper(), path)
        for path, item in app.openapi()["paths"].items()
        if path.startswith("/api/v1")
        for method in item
    }
    assert documented, "openapi lists no routes"
    assert not documented - routes.keys()
    assert ("GET", "/api/v1/applications") in routes


@pytest.mark.usefixtures("migrated_db")
async def test_reviewer_gets_403_on_every_other_route(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Fails closed: a route on neither list is treated as gated. Dependencies
    run before body and path validation, so 403 must win over 422."""
    await _env(client, db_session)
    routes = _walk_routes()
    gated = sorted(routes.keys() - REVIEWER_ALLOWED - NOT_SESSION_GATED)
    assert len(gated) > 50
    holes: list[str] = []
    for method, path in gated:
        resp = await client.request(method, _fill(path), json={})
        detail = resp.json().get("detail") if resp.status_code == 403 else None
        if resp.status_code != 403 or detail not in {RECRUITER_ONLY, ADMIN_ONLY}:
            holes.append(f"{method} {path} -> {resp.status_code} {resp.text[:120]}")
    assert not holes, "\n".join(holes)


@pytest.mark.usefixtures("migrated_db")
async def test_allowlisted_routes_are_not_gated(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _env(client, db_session)
    # sign-out-everywhere ends this session, so it runs last
    ordered = sorted(REVIEWER_ALLOWED, key=lambda key: key[1].endswith("sign-out-everywhere"))
    for method, path in ordered:
        resp = await client.request(method, _fill(path), json={})
        assert resp.status_code != 403, f"{method} {path}: {resp.text}"
        assert resp.status_code != 401, f"{method} {path}: {resp.text}"


@pytest.mark.usefixtures("migrated_db")
async def test_queue_for_reviewer_has_only_own_tasks(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    env = await _env(client, db_session)
    own = await _request_from_admin(client, env, env.reviewer_id)
    other = await _request_from_admin(client, env, env.co.member_id)
    # staff sources fire: a published job without a quiz, a request left waiting
    job = (
        await db_session.execute(
            select(Job).join(Scorecard, Scorecard.job_id == Job.id).where(Scorecard.id == own["id"])
        )
    ).scalar_one()
    job.status = JobStatus.PUBLISHED
    other_row = await db_session.get(Scorecard, other["id"])
    assert other_row is not None
    other_row.due_from = datetime.now(UTC) - timedelta(days=5)
    await db_session.commit()

    staff_kinds = {i["kind"] for i in (await client.get("/api/v1/stats/queue")).json()["items"]}
    assert {"job-quiz", "scorecard-waiting"} <= staff_kinds

    await _login(client, env.reviewer)
    resp = await client.get("/api/v1/stats/queue")
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert [i["key"] for i in items] == [f"scorecard:{own['id']}"]
    assert items[0]["kind"] == "scorecard"
    assert items[0]["href"] == f"/review/{env.co.application_id}"


@pytest.mark.usefixtures("migrated_db")
async def test_reviewer_mine_links_to_review_page_and_submit_works(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    env = await _env(client, db_session)
    await _request_from_admin(client, env, env.reviewer_id)
    await _login(client, env.reviewer)
    mine = (await client.get("/api/v1/scorecards/mine")).json()
    assert [row["application_id"] for row in mine] == [env.co.application_id]
    assert mine[0]["href"].endswith(f"/review/{env.co.application_id}")

    resp = await client.put(
        f"/api/v1/scorecards/applications/{env.co.application_id}/mine",
        json={"ratings": {env.co.criterion_id: 4}, "recommendation": "yes"},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.usefixtures("migrated_db")
async def test_staff_request_to_reviewer_uses_display_label(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    env = await _env(client, db_session)
    await client.patch("/api/v1/users/me", json={"display_name": "Max Keller"})
    row = await _request_from_admin(client, env, env.reviewer_id)
    assert row["reviewer_label"] == "Max Keller"
    listed = await client.get(f"/api/v1/scorecards/applications/{env.co.application_id}")
    assert [r["reviewer_label"] for r in listed.json()] == ["Max Keller"]


@pytest.mark.usefixtures("migrated_db")
async def test_reviewer_reads_the_slim_team_list(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _env(client, db_session)
    team = (await client.get("/api/v1/users")).json()
    assert {u["role"] for u in team} == {"admin", "member", "reviewer"}
    assert all(
        set(u) == {"id", "email", "role", "display_name", "display_label", "is_active"}
        for u in team
    )


@pytest.mark.usefixtures("migrated_db")
async def test_api_key_unaffected(client: AsyncClient, db_session: AsyncSession) -> None:
    env = await _env(client, db_session)
    await _login(client, env.co.admin)
    created = await client.post("/api/v1/api-keys", json={"name": "Sync", "scope": "write"})
    assert created.status_code == 201, created.text
    bearer = {"Authorization": f"Bearer {created.json()['secret']}"}

    # a reviewer cookie alongside the key does not change who is asking
    await _login(client, env.reviewer)
    resp = await client.get("/api/v1/applications", headers=bearer)
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 1
    detail = await client.get(f"/api/v1/applications/{env.co.application_id}", headers=bearer)
    assert detail.status_code == 200, detail.text
    stage = await client.patch(
        f"/api/v1/applications/{env.co.application_id}/stage",
        headers=bearer,
        json={"stage": "screening"},
    )
    assert stage.status_code == 200, stage.text
    assert (await client.get("/api/v1/applications/export", headers=bearer)).status_code == 200


@pytest.mark.usefixtures("migrated_db")
async def test_promotion_and_demotion_keep_rows_and_move_the_gate_at_once(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    env = await _env(client, db_session)
    await _request_from_admin(client, env, env.reviewer_id)

    resp = await client.patch(f"/api/v1/users/{env.reviewer_id}", json={"role": "member"})
    assert resp.status_code == 200, resp.text
    await _login(client, env.reviewer)
    assert (await client.get("/api/v1/applications")).status_code == 200
    assert len((await client.get("/api/v1/scorecards/mine")).json()) == 1

    await _login(client, env.co.admin)
    resp = await client.patch(f"/api/v1/users/{env.co.member_id}", json={"role": "reviewer"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "reviewer"
    await _login(client, env.co.member)
    assert (await client.get("/api/v1/applications")).status_code == 403
    assert (await client.get("/api/v1/stats/queue")).status_code == 200


@pytest.mark.usefixtures("migrated_db")
async def test_live_session_loses_access_when_demoted(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    env = await _env(client, db_session)
    await _login(client, env.co.member)
    assert (await client.get("/api/v1/jobs")).status_code == 200
    me = (await client.get("/api/v1/auth/me")).json()["id"]
    cookies = dict(client.cookies)

    await _login(client, env.co.admin)
    resp = await client.patch(f"/api/v1/users/{me}", json={"role": "reviewer"})
    assert resp.status_code == 200, resp.text

    client.cookies.clear()
    client.cookies.update(cookies)
    assert (await client.get("/api/v1/jobs")).status_code == 403


@pytest.mark.usefixtures("migrated_db")
async def test_last_admin_cannot_become_reviewer(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    env = await _env(client, db_session)
    await _login(client, env.co.admin)
    resp = await client.patch(f"/api/v1/users/{env.co.admin_id}", json={"role": "reviewer"})
    assert resp.status_code == 409, resp.text


def test_team_invite_email_names_the_reviewer_role(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: dict[str, Any] = {}

    def _capture(**kwargs: Any) -> None:
        sent.update(kwargs)

    monkeypatch.setattr(email_service, "send_email", _capture)
    email_service.send_team_invite(
        to="max@ganek-ci.dev",
        company_name="Acme Labs",
        inviter_email="erika@ganek-ci.dev",
        role="reviewer",
        invite_url="http://localhost:3000/invite/tok",
        expires_at=datetime(2026, 11, 8, tzinfo=UTC),
        brand_primary=None,
    )
    assert "as Reviewer" in sent["body"]
