"""Applicant list `waiting` filter (spec PIPELINE_SIGNALS_AND_REPORTS): the same
waiting-on-whom rules as the open roles board, through list, stage pills and export."""

import csv
import io

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_applications_list_filters import _emails, _pipeline, multi_mode  # noqa: F401

pytestmark = pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")


async def test_waiting_team_matches_service_rules(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    emails = await _pipeline(client, db_session)
    # completed quiz, expired link and no quiz wait on the team; a live link on the candidate
    assert set(await _emails(client, waiting="team")) == {
        emails["erika"],
        emails["ben"],
        emails["dan"],
        emails["eve"],
    }
    assert await _emails(client, waiting="candidate") == [emails["cara"]]
    assert await _emails(client, waiting="candidate", q="cara") == [emails["cara"]]
    assert await _emails(client, waiting="team", q="cara") == []


async def test_waiting_composes_with_ids_on_export(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    emails = await _pipeline(client, db_session)
    listed = (await client.get("/api/v1/applications")).json()["items"]
    ids = {row["candidate"]["email"]: row["id"] for row in listed}
    resp = await client.get(
        "/api/v1/applications/export",
        params={"waiting": "team", "ids": f"{ids[emails['erika']]},{ids[emails['cara']]}"},
    )
    assert resp.status_code == 200
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert [row["candidate_email"] for row in rows] == [emails["erika"]]


async def test_waiting_with_no_match_returns_empty_page_and_zero_pills(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    emails = await _pipeline(client, db_session)
    # only cara waits on the candidate: narrow to someone who does not
    page = (
        await client.get("/api/v1/applications", params={"waiting": "candidate", "q": "erika"})
    ).json()
    assert page["items"] == [] and page["total"] == 0
    assert page["stage_counts"] == {}
    # pills honour the filter too
    pills = (await client.get("/api/v1/applications", params={"waiting": "candidate"})).json()
    assert pills["stage_counts"] == {"new": 1}
    assert emails["cara"]


async def test_export_honours_waiting(client: AsyncClient, db_session: AsyncSession) -> None:
    emails = await _pipeline(client, db_session)
    resp = await client.get("/api/v1/applications/export", params={"waiting": "candidate"})
    assert resp.status_code == 200
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert [row["candidate_email"] for row in rows] == [emails["cara"]]
