"""Gate and camera endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import (
    AdminUser,
    CompoundScope,
    CurrentUser,
    ManagerUser,
    PaginationDep,
    SessionDep,
)
from app.core.exceptions import PermissionDeniedError
from app.models.enums import CameraStatus, GateDirection, GateStatus
from app.schemas.access import GateCommandRequest, GateCommandResult
from app.schemas.common import Message, Page
from app.schemas.compound import (
    CameraCreate,
    CameraRead,
    CameraUpdate,
    GateCreate,
    GateRead,
    GateUpdate,
)
from app.services.compound_service import compound_service
from app.services.cv_service import cv_service
from app.services.gate_service import camera_service, gate_service
from app.services.permissions import enforce_compound

router = APIRouter(tags=["Gates & Cameras"])


# --------------------------------------------------------------------- gates
@router.get("/gates", response_model=Page[GateRead], summary="List gates")
async def list_gates(
    session: SessionDep,
    user: CurrentUser,
    pagination: PaginationDep,
    compound_id: CompoundScope,
    status_filter: GateStatus | None = Query(default=None, alias="status"),
    direction: GateDirection | None = Query(default=None),
    search: str | None = Query(default=None, max_length=120),
) -> Page[GateRead]:
    page = await gate_service.list(
        session,
        pagination.to_params(),
        compound_id=compound_id,
        status=status_filter,
        search=search,
    )
    items = page.items
    if direction is not None:
        items = [gate for gate in items if gate.direction == direction]
    return Page[GateRead].create(
        [GateRead.model_validate(item) for item in items],
        page.total,
        page.page,
        page.page_size,
    )


@router.post(
    "/gates",
    response_model=GateRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a gate",
)
async def create_gate(
    payload: GateCreate, session: SessionDep, manager: ManagerUser
) -> GateRead:
    enforce_compound(manager, payload.compound_id)
    await compound_service.get(session, payload.compound_id)
    return GateRead.model_validate(await gate_service.create(session, payload))


@router.get("/gates/{gate_id}", response_model=GateRead, summary="Get a gate")
async def get_gate(gate_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> GateRead:
    gate = await gate_service.get(session, gate_id)
    enforce_compound(user, gate.compound_id)
    return GateRead.model_validate(gate)


@router.patch("/gates/{gate_id}", response_model=GateRead, summary="Update a gate")
async def update_gate(
    gate_id: uuid.UUID, payload: GateUpdate, session: SessionDep, manager: ManagerUser
) -> GateRead:
    gate = await gate_service.get(session, gate_id)
    enforce_compound(manager, gate.compound_id)
    return GateRead.model_validate(await gate_service.update(session, gate_id, payload))


@router.delete("/gates/{gate_id}", response_model=Message, summary="Delete a gate")
async def delete_gate(gate_id: uuid.UUID, session: SessionDep, admin: AdminUser) -> Message:
    gate = await gate_service.get(session, gate_id)
    enforce_compound(admin, gate.compound_id)
    await gate_service.delete(session, gate_id)
    return Message(message=f"Gate {gate.code} deleted")


@router.post(
    "/gates/{gate_id}/command",
    response_model=GateCommandResult,
    summary="Command a barrier (open/close/hold)",
)
async def command_gate(
    gate_id: uuid.UUID,
    payload: GateCommandRequest,
    session: SessionDep,
    manager: ManagerUser,
) -> GateCommandResult:
    gate = await gate_service.get(session, gate_id)
    enforce_compound(manager, gate.compound_id)
    return await cv_service.command_gate(
        session, gate, payload.action, payload.reason, actor=manager.email
    )


# ------------------------------------------------------------------- cameras
@router.get("/cameras", response_model=Page[CameraRead], summary="List cameras")
async def list_cameras(
    session: SessionDep,
    manager: ManagerUser,
    pagination: PaginationDep,
    compound_id: CompoundScope,
    gate_id: uuid.UUID | None = Query(default=None),
    status_filter: CameraStatus | None = Query(default=None, alias="status"),
    is_active: bool | None = Query(default=None),
    search: str | None = Query(default=None, max_length=120),
) -> Page[CameraRead]:
    page = await camera_service.list(
        session,
        pagination.to_params(),
        compound_id=compound_id,
        gate_id=gate_id,
        status=status_filter,
        is_active=is_active,
        search=search,
    )
    return Page[CameraRead].create(
        [CameraRead.model_validate(item) for item in page.items],
        page.total,
        page.page,
        page.page_size,
    )


@router.post(
    "/cameras",
    response_model=CameraRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a camera",
)
async def create_camera(
    payload: CameraCreate, session: SessionDep, manager: ManagerUser
) -> CameraRead:
    gate = await gate_service.get(session, payload.gate_id)
    enforce_compound(manager, gate.compound_id)
    return CameraRead.model_validate(await camera_service.create(session, payload))


@router.get("/cameras/{camera_id}", response_model=CameraRead, summary="Get a camera")
async def get_camera(
    camera_id: uuid.UUID, session: SessionDep, manager: ManagerUser
) -> CameraRead:
    camera = await camera_service.get(session, camera_id)
    gate = await gate_service.get(session, camera.gate_id)
    enforce_compound(manager, gate.compound_id)
    return CameraRead.model_validate(camera)


@router.patch("/cameras/{camera_id}", response_model=CameraRead, summary="Update a camera")
async def update_camera(
    camera_id: uuid.UUID, payload: CameraUpdate, session: SessionDep, manager: ManagerUser
) -> CameraRead:
    camera = await camera_service.get(session, camera_id)
    gate = await gate_service.get(session, camera.gate_id)
    enforce_compound(manager, gate.compound_id)
    return CameraRead.model_validate(await camera_service.update(session, camera_id, payload))


@router.delete("/cameras/{camera_id}", response_model=Message, summary="Delete a camera")
async def delete_camera(
    camera_id: uuid.UUID, session: SessionDep, manager: ManagerUser
) -> Message:
    camera = await camera_service.get(session, camera_id)
    gate = await gate_service.get(session, camera.gate_id)
    enforce_compound(manager, gate.compound_id)
    await camera_service.delete(session, camera_id)
    return Message(message=f"Camera {camera.name} deleted")


@router.post(
    "/cameras/{camera_id}/toggle",
    response_model=CameraRead,
    summary="Enable or disable a camera stream",
)
async def toggle_camera(
    camera_id: uuid.UUID,
    session: SessionDep,
    manager: ManagerUser,
    active: bool = Query(default=True),
) -> CameraRead:
    camera = await camera_service.get(session, camera_id)
    gate = await gate_service.get(session, camera.gate_id)
    if manager.compound_id is not None and manager.compound_id != gate.compound_id:
        raise PermissionDeniedError("You cannot manage cameras of another compound")
    return CameraRead.model_validate(await camera_service.set_active(session, camera_id, active))
