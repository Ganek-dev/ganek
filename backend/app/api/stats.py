from fastapi import APIRouter

from app.api.deps import CurrentCompany, DbSession
from app.schemas.stats import StatsOverview
from app.services import stats as stats_service

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/overview", response_model=StatsOverview)
async def stats_overview(db: DbSession, company: CurrentCompany) -> StatsOverview:
    return await stats_service.overview(db, company)
