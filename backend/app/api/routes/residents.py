"""Resident endpoints."""

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
from app.models.enums import ResidentStatus
from app.schemas.common import Message, Page
from app.schemas.people import ResidentCreate, ResidentRead, ResidentUpdate
from app.services.permissions import compound_scope, enforce_compound, is_manager
from app.services.resident_service import resident_service

router = APIRouter(prefix="/residents", tags=["Residents"])


@router.get("/me", response_model=ResidentRead, summary="My resident profile")
async def my_profile(session: SessionDep, user: CurrentUser) -> ResidentRead:
    """Return the resident profile linked to the authenticated account."""
    profile = await resident_service.get_by_user(session, user.id)
    if profile is None:
        raise PermissionDeniedError("No resident profile is linked to this account")
    await resident_service._attach_counts(session, [profile])  # noqa: SLF001 - internal helper
    return ResidentRead.model_validate(profile)


@router.get("", response_model=Page[ResidentRead], summary="List residents")
async def list_residents(
    session: SessionDep,
    manager: ManagerUser,
    pagination: PaginationDep,
    compound_id: CompoundScope,
    unit_id: uuid.UUID | None = Query(default=None),
    status_filter: ResidentStatus | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=120),
) -> Page[ResidentRead]:
    page = await resident_service.list(
        session,
        pagination.to_params(),
        compound_id=compound_id,
        unit_id=unit_id,
        status=status_filter,
        search=search,
    )
    return Page[ResidentRead].create(
        [ResidentRead.model_validate(item) for item in page.items],
        page.total,
        page.page,
        page.page_size,
    )


@router.post(
    "",
    response_model=ResidentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a resident",
)
async def create_resident(
    payload: ResidentCreate, session: SessionDep, manager: ManagerUser
) -> ResidentRead:
    enforce_compound(manager, payload.compound_id)
    resident = await resident_service.create(session, payload, actor=manager)
    await resident_service._attach_counts(session, [resident])  # noqa: SLF001
    return ResidentRead.model_validate(resident)


@router.get("/{resident_id}", response_model=ResidentRead, summary="Get a resident")
async def get_resident(
    resident_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> ResidentRead:
    resident = await resident_service.get(session, resident_id)
    if not is_manager(user):
        profile = await resident_service.get_by_user(session, user.id)
        if profile is None or profile.id != resident_id:
            raise PermissionDeniedError("You can only view your own profile")
    enforce_compound(user, resident.compound_id)
    await resident_service._attach_counts(session, [resident])  # noqa: SLF001
    return ResidentRead.model_validate(resident)


@router.patch("/{resident_id}", response_model=ResidentRead, summary="Update a resident")
async def update_resident(
    resident_id: uuid.UUID,
    payload: ResidentUpdate,
    session: SessionDep,
    manager: ManagerUser,
) -> ResidentRead:
    resident = await resident_service.get(session, resident_id)
    enforce_compound(manager, resident.compound_id)
    updated = await resident_service.update(session, resident_id, payload)
    await resident_service._attach_counts(session, [updated])  # noqa: SLF001
    return ResidentRead.model_validate(updated)


@router.delete("/{resident_id}", response_model=Message, summary="Delete a resident")
async def delete_resident(
    resident_id: uuid.UUID, session: SessionDep, manager: ManagerUser
) -> Message:
    resident = await resident_service.get(session, resident_id)
    enforce_compound(manager, resident.compound_id)
    await resident_service.delete(session, resident_id)
    return Message(message=f"Resident {resident.full_name} deleted")
