"""Company-level applicant export (card D9): CSV/JSON of the current filter,
admin only, flat rows without internal ids, one activity entry per export."""

import csv
import io
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.db import database_reachable, s3_reachable
from tests.test_admin_applications_api import _company_with_applicant

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_csv_export_follows_filters_and_leaks_no_ids(client: AsyncClient) -> None:
    job_id, email = await _company_with_applicant(client)
    listed = (await client.get("/api/v1/applications")).json()["items"]
    application = listed[0]

    resp = await client.get("/api/v1/applications/export", params={"format": "csv"})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.headers["content-disposition"].endswith('.csv"')
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert len(rows) == 1
    row = rows[0]
    assert row["candidate_name"] == "Jane Applicant"
    assert row["candidate_email"] == email
    assert row["job"] == "Backend Engineer"
    assert row["stage"] == "new"
    assert row["quiz_status"] == ""  # no assessment on this job
    assert row["applied_at"]
    # internal ids and anything quiz-internal never leave the server
    for secret in (application["id"], job_id, application["candidate"]["id"], "correct_key"):
        assert secret not in resp.text

    # the stage filter narrows, a foreign job id matches nothing
    assert (
        len(
            list(
                csv.DictReader(
                    io.StringIO(
                        (
                            await client.get(
                                "/api/v1/applications/export",
                                params={"format": "csv", "stage": "rejected"},
                            )
                        ).text
                    )
                )
            )
        )
        == 0
    )
    other = (
        await client.get(
            "/api/v1/applications/export", params={"format": "csv", "job_id": str(uuid4())}
        )
    ).text
    assert list(csv.DictReader(io.StringIO(other))) == []


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_json_export_matches_csv_columns_and_is_logged(client: AsyncClient) -> None:
    _job_id, email = await _company_with_applicant(client)
    resp = await client.get("/api/v1/applications/export", params={"format": "json"})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.headers["content-disposition"].endswith('.json"')
    rows = resp.json()
    assert len(rows) == 1 and rows[0]["candidate_email"] == email
    csv_header = (
        (await client.get("/api/v1/applications/export", params={"format": "csv"}))
        .text.splitlines()[0]
        .split(",")
    )
    assert list(rows[0]) == csv_header

    activity = (await client.get("/api/v1/activity")).json()
    exports = [a for a in activity if a["type"] == "applications.exported"]
    assert len(exports) == 2  # json + csv above
    assert exports[0]["payload"] == {
        "format": "csv",
        "rows": 1,
        "stage": None,
        "job_id": None,
        "filtered": False,
    }
    assert exports[0]["actor_email"] is not None


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_export_follows_search_and_quiz_filters(client: AsyncClient) -> None:
    """The file is always the rows on screen: every list filter applies."""
    _job_id, email = await _company_with_applicant(client)

    def _rows(text: str) -> list[dict[str, str]]:
        return list(csv.DictReader(io.StringIO(text)))

    hit = await client.get("/api/v1/applications/export", params={"format": "csv", "q": "JANE"})
    assert hit.status_code == 200, hit.text
    assert [row["candidate_email"] for row in _rows(hit.text)] == [email]
    miss = await client.get("/api/v1/applications/export", params={"format": "csv", "q": "nobody"})
    assert _rows(miss.text) == []
    # this job has no assessment, so a quiz-state filter empties the file
    none = await client.get(
        "/api/v1/applications/export", params={"format": "csv", "quiz": "completed"}
    )
    assert _rows(none.text) == []
    assert (
        await client.get("/api/v1/applications/export", params={"format": "csv", "score_min": 101})
    ).status_code == 422


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_export_ids_selects_rows_and_caps_at_100(client: AsyncClient) -> None:
    """`ids=` is the bulk bar's "Export CSV": the checked rows, same cap as
    bulk reject, foreign and unknown ids silently absent."""
    _job_id, email = await _company_with_applicant(client)
    application_id = (await client.get("/api/v1/applications")).json()["items"][0]["id"]

    def _rows(text: str) -> list[dict[str, str]]:
        return list(csv.DictReader(io.StringIO(text)))

    picked = await client.get(
        "/api/v1/applications/export",
        params={"format": "csv", "ids": f"{application_id},{uuid4()}"},
    )
    assert picked.status_code == 200, picked.text
    assert [row["candidate_email"] for row in _rows(picked.text)] == [email]
    empty = await client.get(
        "/api/v1/applications/export", params={"format": "csv", "ids": str(uuid4())}
    )
    assert _rows(empty.text) == []
    too_many = ",".join(str(uuid4()) for _ in range(101))
    assert (
        await client.get("/api/v1/applications/export", params={"format": "csv", "ids": too_many})
    ).status_code == 422
    assert (
        await client.get(
            "/api/v1/applications/export", params={"format": "csv", "ids": "not-a-uuid"}
        )
    ).status_code == 422
    # the export receipt notes that a filter or selection was applied
    activity = (await client.get("/api/v1/activity")).json()
    exports = [a for a in activity if a["type"] == "applications.exported"]
    assert exports[0]["payload"]["filtered"] is True
