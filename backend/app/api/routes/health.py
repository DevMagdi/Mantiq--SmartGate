"""Liveness and readiness endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app import __version__
from app.core.cache import check_redis
from app.core.config import settings
from app.db.session import check_database
from app.schemas.common import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    """Cheap liveness check used by container orchestrators."""
    return {
        "status": "ok",
        "version": __version__,
        "environment": settings.ENVIRONMENT,
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get(
    "/health/ready",
    response_model=HealthResponse,
    summary="Readiness probe",
    responses={503: {"description": "A dependency is unavailable"}},
)
async def readiness() -> HealthResponse | JSONResponse:
    """Verify that the database (and Redis when enabled) are reachable."""
    database_ok = await check_database()
    redis_ok = await check_redis()
    healthy = database_ok and (redis_ok or not settings.REDIS_ENABLED)
    payload = HealthResponse(
        status="ready" if healthy else "degraded",
        version=__version__,
        environment=settings.ENVIRONMENT,
        database=database_ok,
        redis=redis_ok,
        cv_mode=settings.CV_MODE,
        timestamp=datetime.now(UTC),
    )
    if not healthy:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=payload.model_dump(mode="json"),
        )
    return payload
