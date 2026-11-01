"""Liveness and readiness endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, select

from app import __version__
from app.core.cache import check_redis
from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import render_metrics
from app.cv.actuators import actuator_registry
from app.cv.engine import get_vision_engine
from app.cv.manager import get_camera_manager
from app.cv.runner import read_heartbeat
from app.models.compound import Camera, Gate
from app.models.enums import CameraStatus
from app.db.session import check_database
from app.db.session import session_scope
from app.models.security import FaceEmbedding
from app.schemas.common import HealthResponse

logger = get_logger(__name__)

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


@router.get("/health/live", include_in_schema=False)
async def liveness_alias() -> dict[str, str]:
    """Alias used by some orchestrators/load balancers."""
    return {"status": "ok", "version": __version__}


@router.get(
    "/metrics",
    include_in_schema=False,
    responses={200: {"content": {"text/plain": {}}}},
)
async def metrics() -> Response:
    """Prometheus exposition endpoint (scrape every 15–30 s)."""
    payload, content_type = render_metrics()
    return Response(content=payload, media_type=content_type)


@router.get(
    "/health/ready",
    response_model=HealthResponse,
    summary="Readiness probe",
    responses={503: {"description": "A dependency is unavailable"}},
)
async def readiness() -> HealthResponse | JSONResponse:
    """Verify dependencies and report the state of the vision/barrier stack.

    Only the database and (when enabled) Redis decide readiness: a missing CV
    model must not take the dashboard and the audit trail offline, it is
    reported as a warning instead.
    """
    database_ok = await check_database()
    redis_ok = await check_redis()
    engine = get_vision_engine().status()
    gallery_entries: int | None = None
    warnings: list[str] = []
    if database_ok:
        try:
            async with session_scope() as session:
                gallery_entries = int(
                    await session.scalar(
                        select(func.count(FaceEmbedding.id)).where(
                            FaceEmbedding.is_active.is_(True)
                        )
                    )
                    or 0
                )
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Could not count embeddings for readiness: %s", exc)
    if settings.CV_ENABLED and settings.CV_MODE == "real" and not engine["engine_ready"]:
        warnings.append("Vision engine is not ready; detections will fail until models load")
    warnings.extend(str(item) for item in engine.get("warnings", [])[:5])

    # ------------------------------------------------ cameras & CV heartbeat
    camera_counts: dict[str, int] = {"total": 0, "online": 0, "offline": 0, "error": 0}
    if database_ok:
        try:
            async with session_scope() as session:
                rows = (
                    await session.execute(
                        select(Camera.status, func.count(Camera.id))
                        .join(Gate, Camera.gate_id == Gate.id)
                        .group_by(Camera.status)
                    )
                ).all()
            for status_value, count in rows:
                key = str(status_value)
                camera_counts["total"] += count
                if key == CameraStatus.ONLINE.value:
                    camera_counts["online"] += count
                elif key == CameraStatus.ERROR.value:
                    camera_counts["error"] += count
                elif key == CameraStatus.OFFLINE.value:
                    camera_counts["offline"] += count
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Could not count cameras for readiness: %s", exc)
    manager = get_camera_manager()
    workers = []
    if manager is not None:
        try:
            workers = list(manager.status().get("workers", []))  # type: ignore[arg-type]
        except Exception:  # pragma: no cover - defensive
            workers = []
    heartbeat = read_heartbeat()
    in_process = bool(settings.CV_ENABLED and settings.CV_RUNNER_ENABLED)
    worker_ok = (bool(heartbeat.get("fresh")) or bool(workers)) if settings.CV_ENABLED else True
    if settings.CV_ENABLED and settings.CV_MODE == "real":
        if camera_counts["total"] and camera_counts["online"] == 0:
            warnings.append("No camera is online; check the RTSP URLs under Settings → Cameras")
        if not worker_ok and not in_process:
            warnings.append("CV runner heartbeat is stale; the cv-worker container is not reporting")

    checks: dict[str, object] = {
        "database": {"ok": database_ok},
        "redis": {"ok": redis_ok, "enabled": settings.REDIS_ENABLED},
        "vision": {
            "enabled": settings.CV_ENABLED,
            "mode": settings.CV_MODE,
            "engine_ready": bool(engine["engine_ready"]),
            "models_loaded": list(engine.get("models_loaded", [])),
            "face_gallery_size": gallery_entries,
        },
        "barrier": {
            "default_driver": settings.BARRIER_DRIVER,
            "compounds": actuator_registry.active_compounds,
        },
        "cameras": {
            "total": camera_counts["total"],
            "online": camera_counts["online"],
            "offline": camera_counts["offline"],
            "error": camera_counts["error"],
            "workers": len(workers),
        },
        "cv_worker": {
            "enabled": settings.CV_ENABLED,
            "runner_enabled": settings.CV_RUNNER_ENABLED,
            "heartbeat": heartbeat,
            "in_process_workers": len(workers),
            "healthy": worker_ok,
        },
        "maintenance": {"enabled": settings.MAINTENANCE_ENABLED},
    }
    healthy = database_ok and (redis_ok or not settings.REDIS_ENABLED)
    payload = HealthResponse(
        status="ready" if healthy else "degraded",
        version=__version__,
        environment=settings.ENVIRONMENT,
        database=database_ok,
        redis=redis_ok,
        cv_mode=settings.CV_MODE,
        timestamp=datetime.now(UTC),
        checks=checks,
        warnings=list(dict.fromkeys(warnings)),
    )
    if not healthy:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=payload.model_dump(mode="json"),
        )
    return payload
