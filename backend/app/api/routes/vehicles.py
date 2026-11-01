"""Vehicle endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import (
    CompoundScope,
    CurrentUser,
    ManagerUser,
    PaginationDep,
    SessionDep,
)
from app.core.exceptions import PermissionDeniedError
from app.models.enums import VehicleStatus
from app.schemas.common import Message, Page
from app.schemas.vehicle import VehicleCreate, VehicleRead, VehicleUpdate
from app.services.permissions import compound_scope, enforce_compound, is_manager
from app.services.resident_service import resident_service
from app.services.vehicle_service import vehicle_service

router = APIRouter(prefix="/vehicles", tags=["Vehicles"])


@router.get("", response_model=Page[VehicleRead], summary="List vehicles")
async def list_vehicles(
    session: SessionDep,
    user: CurrentUser,
    pagination: PaginationDep,
    compound_id: CompoundScope,
    resident_id: uuid.UUID | None = Query(default=None),
    status_filter: VehicleStatus | None = Query(default=None, alias="status"),
    is_inside: bool | None = Query(default=None),
    search: str | None = Query(default=None, max_length=120),
) -> Page[VehicleRead]:
    if is_manager(user):
        scope = compound_id
    else:
        profile = await resident_service.get_by_user(session, user.id)
        if profile is None:
            raise PermissionDeniedError("No resident profile is linked to this account")
        scope = profile.compound_id
        resident_id = profile.id
    page = await vehicle_service.list(
        session,
        pagination.to_params(),
        compound_id=scope,
        resident_id=resident_id,
        status=status_filter,
        is_inside=is_inside,
        search=search,
    )
    return Page[VehicleRead].create(
        [VehicleRead.model_validate(item) for item in page.items],
        page.total,
        page.page,
        page.page_size,
    )


@router.post(
    "",
    response_model=VehicleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a vehicle",
)
async def create_vehicle(
    payload: VehicleCreate, session: SessionDep, manager: ManagerUser
) -> VehicleRead:
    enforce_compound(manager, payload.compound_id)
    return VehicleRead.model_validate(await vehicle_service.create(session, payload))


@router.get("/{vehicle_id}", response_model=VehicleRead, summary="Get a vehicle")
async def get_vehicle(
    vehicle_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> VehicleRead:
    vehicle = await vehicle_service.get(session, vehicle_id)
    enforce_compound(user, vehicle.compound_id)
    if not is_manager(user):
        profile = await resident_service.get_by_user(session, user.id)
        if profile is None or vehicle.resident_id != profile.id:
            raise PermissionDeniedError("You can only view your own vehicles")
    return VehicleRead.model_validate(vehicle)


@router.patch("/{vehicle_id}", response_model=VehicleRead, summary="Update a vehicle")
async def update_vehicle(
    vehicle_id: uuid.UUID, payload: VehicleUpdate, session: SessionDep, manager: ManagerUser
) -> VehicleRead:
    vehicle = await vehicle_service.get(session, vehicle_id)
    enforce_compound(manager, vehicle.compound_id)
    return VehicleRead.model_validate(await vehicle_service.update(session, vehicle_id, payload))


@router.delete("/{vehicle_id}", response_model=Message, summary="Delete a vehicle")
async def delete_vehicle(
    vehicle_id: uuid.UUID, session: SessionDep, manager: ManagerUser
) -> Message:
    vehicle = await vehicle_service.get(session, vehicle_id)
    enforce_compound(manager, vehicle.compound_id)
    await vehicle_service.delete(session, vehicle_id)
    return Message(message=f"Vehicle {vehicle.plate_number} deleted")
