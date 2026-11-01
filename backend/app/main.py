"""GateVision FastAPI application factory and lifespan management."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import __version__
from app.api.errors import register_exception_handlers
from app.api.middleware import RequestContextMiddleware
from app.api.routes import api_router
from app.api.routes import health as health_routes
from app.core.cache import close_cache
from app.core.config import settings
from app.core.events import get_event_bus, shutdown_event_bus
from app.core.logging import configure_logging, get_logger
from app.core.metrics import set_app_info, set_engine_state
from app.cv.engine import get_vision_engine
from app.cv.manager import CameraManager, set_camera_manager
from app.db.session import dispose_engine, get_engine
from app.services.detection_service import detection_service
from app.tasks.maintenance import maintenance_loop

logger = get_logger(__name__)

OPENAPI_TAGS = [
    {"name": "Authentication", "description": "JWT login, refresh and profile endpoints."},
    {"name": "Users", "description": "Account administration (admins only)."},
    {"name": "Compounds & Units", "description": "Compounds, units and occupancy."},
    {"name": "Gates & Cameras", "description": "Physical gates, barriers and camera streams."},
    {"name": "Residents", "description": "Resident registry and portal profile."},
    {"name": "Vehicles", "description": "Vehicle registry and plate records."},
    {"name": "Visitors", "description": "Visitor invitations, approvals and check-in/out."},
    {"name": "Permits", "description": "Temporary permits with expiry and entry limits."},
    {"name": "Blacklist", "description": "Plate, face and person blacklists."},
    {"name": "Face Recognition", "description": "Face enrollment and gallery management."},
    {"name": "Access Control", "description": "Access logs, detections, overrides and exports."},
    {"name": "Analytics", "description": "Dashboard KPIs and time-series analytics."},
    {"name": "Computer Vision", "description": "Vision engine status, warmup and image analysis."},
    {"name": "Realtime", "description": "WebSocket stream of detections and decisions."},
    {"name": "Health", "description": "Liveness and readiness probes."},
]


async def _startup_tasks(app: FastAPI) -> None:
    settings.ensure_directories()
    for warning in settings.validate_production():
        logger.warning("Configuration: %s", warning)
    if settings.AUTO_CREATE_TABLES:
        from app.models import Base

        async with get_engine().begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        logger.info("Database schema ensured (AUTO_CREATE_TABLES=true)")

    if settings.SEED_DEMO_DATA:
        try:
            from app.services.seed_service import seed_demo_data

            stats = await seed_demo_data()
            logger.info("Startup seeding completed: %s", stats)
        except Exception:  # pragma: no cover - defensive: never block boot on seed
            logger.exception("Startup seeding failed; continuing without demo data")

    set_app_info(__version__, settings.ENVIRONMENT, settings.CV_MODE)
    set_engine_state(ready=settings.CV_MODE == "mock", mode=settings.CV_MODE)
    await get_event_bus().start()
    if settings.MAINTENANCE_ENABLED:
        app.state.maintenance_task = asyncio.create_task(
            maintenance_loop(settings.MAINTENANCE_INTERVAL_SECONDS), name="maintenance"
        )

    if settings.CV_ENABLED:
        async def _warm_engine() -> bool:
            engine = get_vision_engine()
            ready = await engine.warmup_async()
            status = engine.status()
            set_engine_state(ready=ready, mode=str(status["mode"]))
            return ready

        app.state.cv_warmup_task = asyncio.create_task(_warm_engine(), name="cv-warmup")
    if settings.CV_ENABLED and settings.CV_RUNNER_ENABLED:
        manager = CameraManager(
            engine=get_vision_engine(), on_result=detection_service.handle_envelope
        )
        await manager.start()
        set_camera_manager(manager)
        app.state.camera_manager = manager
        logger.info("In-process camera manager started")


async def _shutdown_tasks(app: FastAPI) -> None:
    manager: CameraManager | None = getattr(app.state, "camera_manager", None)
    if manager is not None:
        await manager.stop()
        set_camera_manager(None)
    maintenance_task: asyncio.Task[None] | None = getattr(app.state, "maintenance_task", None)
    if maintenance_task is not None:
        maintenance_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await maintenance_task
    warmup_task: asyncio.Task[bool] | None = getattr(app.state, "cv_warmup_task", None)
    if warmup_task is not None and not warmup_task.done():
        warmup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await warmup_task
    await shutdown_event_bus()
    await close_cache()
    await dispose_engine()
    logger.info("GateVision shutdown complete")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup/shutdown of background services."""
    configure_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)
    logger.info("Starting %s %s (%s)", settings.APP_NAME, __version__, settings.ENVIRONMENT)
    await _startup_tasks(app)
    try:
        yield
    finally:
        await _shutdown_tasks(app)


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    app = FastAPI(
        title=settings.APP_NAME,
        description=(
            "Smart gate management platform with real-time license plate recognition, "
            "face recognition and rule-based access decisions."
        ),
        version=__version__,
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_tags=OPENAPI_TAGS,
        contact={"name": "GateVision Engineering", "email": "engineering@gatevision.app"},
        license_info={"name": "MIT"},
        lifespan=lifespan,
    )

    settings.ensure_directories()
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition", "X-Request-ID"],
    )
    if "*" not in settings.TRUSTED_HOSTS:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.TRUSTED_HOSTS)

    register_exception_handlers(app)
    app.mount(
        settings.MEDIA_URL,
        StaticFiles(directory=str(settings.MEDIA_ROOT), check_dir=False),
        name="media",
    )
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)
    app.include_router(health_routes.router, include_in_schema=False)

    @app.get("/", include_in_schema=False)
    async def root() -> JSONResponse:
        return JSONResponse(
            {
                "name": settings.APP_NAME,
                "version": __version__,
                "environment": settings.ENVIRONMENT,
                "docs": "/docs",
                "api": settings.API_V1_PREFIX,
                "health": "/health",
            }
        )

    return app


app = create_app()
