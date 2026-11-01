"""Router registry."""

from fastapi import APIRouter

from app.api.routes import (
    access,
    analytics,
    auth,
    blacklist,
    compounds,
    cv,
    faces,
    gates,
    health,
    permits,
    residents,
    users,
    vehicles,
    visitors,
    ws,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(compounds.router)
api_router.include_router(gates.router)
api_router.include_router(residents.router)
api_router.include_router(vehicles.router)
api_router.include_router(visitors.router)
api_router.include_router(permits.router)
api_router.include_router(blacklist.router)
api_router.include_router(faces.router)
api_router.include_router(access.router)
api_router.include_router(analytics.router)
api_router.include_router(cv.router)
api_router.include_router(health.router)
api_router.include_router(ws.router)

__all__ = ["api_router"]
