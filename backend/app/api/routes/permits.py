"""Temporary permit endpoints."""

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
from app.core.exceptions import BadRequestError, PermissionDeniedError
from app.models.enums import PermitStatus
from app.schemas.common import Message, Page
from app.schemas.people import PermitCreate, PermitRead, PermitRevoke, PermitUpdate
from app.services.permissions import enforce_compound, is_manager
from app.services.resident_service import resident_service
from app.services.visitor_service import permit_service, visitor_service

router = APIRouter(prefix="/permits", tags=["Permits"])


@router.get("", response_model=Page[PermitRead], summary="List permits")
async def list_permits(
    session: SessionDep,
    user: CurrentUser,
    pagination: PaginationDep,
    compound_id: CompoundScope,
    status_filter: PermitStatus | None = Query(default=None, alias="status"),
    visitor_id: uuid.UUID | None = Query(default=None),
    host_unit_id: uuid.UUID | None = Query(default=None),
    active_only: bool = Query(default=False),
    search: str | None = Query(default=None, max_length=120),
) -> Page[PermitRead]:
    if is_manager(user):
        scope = compound_id
    else:
        profile = await resident_service.get_by_user(session, user.id)
        if profile is None:
            raise PermissionDeniedError("No resident profile is linked to this account")
        scope = profile.compound_id
        host_unit_id = profile.unit_id
    page = await permit_service.list(
        session,
        pagination.to_params(),
        compound_id=scope,
        status=status_filter,
        visitor_id=visitor_id,
        host_unit_id=host_unit_id,
        active_only=active_only,
        search=search,
    )
    return Page[PermitRead].create(
        [PermitRead.model_validate(item) for item in page.items],
        page.total,
        page.page,
        page.page_size,
    )


@router.post(
    "",
    response_model=PermitRead,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a permit",
)
async def create_permit(
    payload: PermitCreate, session: SessionDep, manager: ManagerUser
) -> PermitRead:
    visitor = await visitor_service.get(session, payload.visitor_id)
    enforce_compound(manager, visitor.compound_id)
    permit = await permit_service.create(session, payload, actor_id=manager.id)
    return PermitRead.model_validate(permit)


@router.post(
    "/visitors/{visitor_id}",
    response_model=PermitRead,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a permit for a visitor",
)
async def create_permit_for_visitor(
    visitor_id: uuid.UUID,
    payload: PermitCreate,
    session: SessionDep,
    manager: ManagerUser,
) -> PermitRead:
    visitor = await visitor_service.get(session, visitor_id)
    enforce_compound(manager, visitor.compound_id)
    if payload.visitor_id != visitor_id:
        raise BadRequestError("Visitor id mismatch")
    permit = await permit_service.create(session, payload, actor_id=manager.id)
    return PermitRead.model_validate(permit)


@router.get("/{permit_id}", response_model=PermitRead, summary="Get a permit")
async def get_permit(
    permit_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> PermitRead:
    permit = await permit_service.get(session, permit_id)
    enforce_compound(user, permit.compound_id)
    if not is_manager(user):
        profile = await resident_service.get_by_user(session, user.id)
        if profile is None or permit.host_unit_id != profile.unit_id:
            raise PermissionDeniedError("You can only view permits for your own unit")
    return PermitRead.model_validate(permit)


@router.patch("/{permit_id}", response_model=PermitRead, summary="Update a permit")
async def update_permit(
    permit_id: uuid.UUID, payload: PermitUpdate, session: SessionDep, manager: ManagerUser
) -> PermitRead:
    permit = await permit_service.get(session, permit_id)
    enforce_compound(manager, permit.compound_id)
    return PermitRead.model_validate(await permit_service.update(session, permit_id, payload))


@router.post("/{permit_id}/revoke", response_model=PermitRead, summary="Revoke a permit")
async def revoke_permit(
    permit_id: uuid.UUID,
    payload: PermitRevoke,
    session: SessionDep,
    manager: ManagerUser,
) -> PermitRead:
    permit = await permit_service.get(session, permit_id)
    enforce_compound(manager, permit.compound_id)
    return PermitRead.model_validate(
        await permit_service.revoke(session, permit_id, payload.reason, actor_id=manager.id)
    )


@router.delete("/{permit_id}", response_model=Message, summary="Delete a permit")
async def delete_permit(
    permit_id: uuid.UUID, session: SessionDep, manager: ManagerUser
) -> Message:
    permit = await permit_service.get(session, permit_id)
    enforce_compound(manager, permit.compound_id)
    await permit_service.delete(session, permit_id)
    return Message(message=f"Permit {permit.permit_code} deleted")
