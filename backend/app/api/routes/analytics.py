"""Analytics endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import CompoundScope, ManagerUser, SessionDep
from app.models.enums import AccessDirection
from app.schemas.analytics import (
    DashboardResponse,
    OccupancySnapshot,
    OverviewStats,
    TrendPoint,
)
from app.services.analytics_service import analytics_service

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/dashboard", response_model=DashboardResponse, summary="Dashboard snapshot")
async def dashboard(
    session: SessionDep,
    manager: ManagerUser,
    compound_id: CompoundScope,
    days: int = Query(default=7, ge=1, le=90),
) -> DashboardResponse:
    """Aggregated KPIs, trends and recent activity for the dashboard."""
    return await analytics_service.dashboard(session, compound_id=compound_id, days=days)


@router.get("/overview", response_model=OverviewStats, summary="Headline KPIs")
async def overview(
    session: SessionDep, manager: ManagerUser, compound_id: CompoundScope
) -> OverviewStats:
    result = await analytics_service.dashboard(session, compound_id=compound_id, days=1)
    return result.overview


@router.get("/trend", response_model=list[TrendPoint], summary="Daily decision trend")
async def trend(
    session: SessionDep,
    manager: ManagerUser,
    compound_id: CompoundScope,
    days: int = Query(default=7, ge=1, le=90),
    direction: AccessDirection | None = Query(default=None),
) -> list[TrendPoint]:
    return await analytics_service.trend(
        session, compound_id=compound_id, days=days, direction=direction
    )


@router.get("/occupancy", response_model=OccupancySnapshot, summary="Live occupancy")
async def occupancy(
    session: SessionDep, manager: ManagerUser, compound_id: CompoundScope
) -> OccupancySnapshot:
    return await analytics_service.occupancy(session, compound_id=compound_id)


@router.get("/blacklist-breakdown", summary="Active blacklist entries by type")
async def blacklist_breakdown(
    session: SessionDep, manager: ManagerUser, compound_id: CompoundScope
) -> dict[str, Any]:
    return await analytics_service.blacklist_breakdown(session, compound_id=compound_id)
