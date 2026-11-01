"""Compound and unit endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import (
    AdminUser,
    CurrentUser,
    ManagerUser,
    PaginationDep,
    SessionDep,
)
from app.core.exceptions import PermissionDeniedError
from app.models.enums import UnitStatus, UnitType
from app.schemas.common import Message, Page
from app.schemas.compound import (
    CompoundCreate,
    CompoundRead,
    CompoundUpdate,
    UnitCreate,
    UnitRead,
    UnitUpdate,
)
from app.services.compound_service import compound_service, unit_service
from app.services.permissions import compound_scope, enforce_compound, is_admin

router = APIRouter(prefix="/compounds", tags=["Compounds & Units"])


@router.get("", response_model=Page[CompoundRead], summary="List compounds")
async def list_compounds(
    session: SessionDep,
    user: CurrentUser,
    pagination: PaginationDep,
    compound_id: uuid.UUID | None = Query(default=None, description="Restrict to a compound"),
    is_active: bool | None = Query(default=None),
    search: str | None = Query(default=None, max_length=120),
) -> Page[CompoundRead]:
    scope = compound_scope(user, compound_id)
    page = await compound_service.list(
        session,
        pagination.to_params(),
        compound_id=scope,
        is_active=is_active,
        search=search,
    )
    return Page[CompoundRead].create(
        [CompoundRead.model_validate(item) for item in page.items],
        page.total,
        page.page,
        page.page_size,
    )


@router.post(
    "",
    response_model=CompoundRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a compound",
)
async def create_compound(
    payload: CompoundCreate, session: SessionDep, admin: AdminUser
) -> CompoundRead:
    return CompoundRead.model_validate(await compound_service.create(session, payload))


@router.get("/{compound_id}", response_model=CompoundRead, summary="Get a compound")
async def get_compound(
    compound_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> CompoundRead:
    if not is_admin(user) and user.compound_id != compound_id:
        raise PermissionDeniedError("You cannot access another compound")
    return CompoundRead.model_validate(await compound_service.get(session, compound_id))


@router.patch("/{compound_id}", response_model=CompoundRead, summary="Update a compound")
async def update_compound(
    compound_id: uuid.UUID,
    payload: CompoundUpdate,
    session: SessionDep,
    admin: AdminUser,
) -> CompoundRead:
    return CompoundRead.model_validate(
        await compound_service.update(session, compound_id, payload)
    )


@router.delete("/{compound_id}", response_model=Message, summary="Delete a compound")
async def delete_compound(
    compound_id: uuid.UUID, session: SessionDep, admin: AdminUser
) -> Message:
    await compound_service.delete(session, compound_id)
    return Message(message="Compound deleted")


@router.get(
    "/{compound_id}/units",
    response_model=Page[UnitRead],
    summary="List units of a compound",
)
async def list_units(
    compound_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    pagination: PaginationDep,
    status_filter: UnitStatus | None = Query(default=None, alias="status"),
    building: str | None = Query(default=None, max_length=50),
    unit_type: UnitType | None = Query(default=None),
    search: str | None = Query(default=None, max_length=120),
) -> Page[UnitRead]:
    enforce_compound(user, compound_id)
    page = await unit_service.list(
        session,
        pagination.to_params(),
        compound_id=compound_id,
        status=status_filter,
        building=building,
        search=search,
    )
    return Page[UnitRead].create(
        [UnitRead.model_validate(item) for item in page.items],
        page.total,
        page.page,
        page.page_size,
    )


@router.post(
    "/{compound_id}/units",
    response_model=UnitRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a unit",
)
async def create_unit(
    compound_id: uuid.UUID,
    payload: UnitCreate,
    session: SessionDep,
    manager: ManagerUser,
) -> UnitRead:
    enforce_compound(manager, compound_id)
    if payload.compound_id is not None and payload.compound_id != compound_id:
        raise PermissionDeniedError("Compound id mismatch")
    payload = payload.model_copy(update={"compound_id": compound_id})
    return UnitRead.model_validate(await unit_service.create(session, payload))


@router.get("/{compound_id}/units/{unit_id}", response_model=UnitRead, summary="Get a unit")
async def get_unit(
    compound_id: uuid.UUID, unit_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> UnitRead:
    enforce_compound(user, compound_id)
    unit = await unit_service.get(session, unit_id)
    if unit.compound_id != compound_id:
        raise PermissionDeniedError("Unit belongs to another compound")
    return UnitRead.model_validate(unit)


@router.patch(
    "/{compound_id}/units/{unit_id}", response_model=UnitRead, summary="Update a unit"
)
async def update_unit(
    compound_id: uuid.UUID,
    unit_id: uuid.UUID,
    payload: UnitUpdate,
    session: SessionDep,
    manager: ManagerUser,
) -> UnitRead:
    enforce_compound(manager, compound_id)
    unit = await unit_service.get(session, unit_id)
    if unit.compound_id != compound_id:
        raise PermissionDeniedError("Unit belongs to another compound")
    return UnitRead.model_validate(await unit_service.update(session, unit_id, payload))


@router.delete(
    "/{compound_id}/units/{unit_id}", response_model=Message, summary="Delete a unit"
)
async def delete_unit(
    compound_id: uuid.UUID, unit_id: uuid.UUID, session: SessionDep, manager: ManagerUser
) -> Message:
    enforce_compound(manager, compound_id)
    unit = await unit_service.get(session, unit_id)
    if unit.compound_id != compound_id:
        raise PermissionDeniedError("Unit belongs to another compound")
    await unit_service.delete(session, unit_id)
    return Message(message=f"Unit {unit.label} deleted")
