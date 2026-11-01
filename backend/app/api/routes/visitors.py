"""Visitor endpoints including the resident self-service flow."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Query, UploadFile, status

from app.api.deps import (
    CompoundScope,
    CurrentUser,
    ManagerUser,
    PaginationDep,
    SessionDep,
)
from app.core.exceptions import BadRequestError, PermissionDeniedError
from app.models.enums import VisitorStatus
from app.schemas.common import Message, Page
from app.schemas.people import VisitorCreate, VisitorRead, VisitorUpdate
from app.services.permissions import enforce_compound, is_manager
from app.services.resident_service import resident_service
from app.services.visitor_service import visitor_service

router = APIRouter(prefix="/visitors", tags=["Visitors"])


async def _resident_scope(session, user):  # type: ignore[no-untyped-def]
    profile = await resident_service.get_by_user(session, user.id)
    if profile is None:
        raise PermissionDeniedError("No resident profile is linked to this account")
    return profile


@router.get("", response_model=Page[VisitorRead], summary="List visitors")
async def list_visitors(
    session: SessionDep,
    user: CurrentUser,
    pagination: PaginationDep,
    compound_id: CompoundScope,
    status_filter: VisitorStatus | None = Query(default=None, alias="status"),
    host_unit_id: uuid.UUID | None = Query(default=None),
    host_resident_id: uuid.UUID | None = Query(default=None),
    active_only: bool = Query(default=False),
    search: str | None = Query(default=None, max_length=120),
) -> Page[VisitorRead]:
    if is_manager(user):
        scope = compound_id
    else:
        profile = await _resident_scope(session, user)
        scope = profile.compound_id
        host_unit_id = profile.unit_id
    page = await visitor_service.list(
        session,
        pagination.to_params(),
        compound_id=scope,
        status=status_filter,
        host_unit_id=host_unit_id,
        host_resident_id=host_resident_id,
        active_only=active_only,
        search=search,
    )
    return Page[VisitorRead].create(
        [VisitorRead.model_validate(item) for item in page.items],
        page.total,
        page.page,
        page.page_size,
    )


@router.post(
    "",
    response_model=VisitorRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a visitor",
)
async def create_visitor(
    payload: VisitorCreate, session: SessionDep, user: CurrentUser
) -> VisitorRead:
    if is_manager(user):
        enforce_compound(user, payload.compound_id)
        visitor = await visitor_service.create(session, payload, actor_id=user.id)
    else:
        profile = await _resident_scope(session, user)
        payload = payload.model_copy(
            update={
                "compound_id": profile.compound_id,
                "host_unit_id": profile.unit_id,
                "host_resident_id": profile.id,
            }
        )
        visitor = await visitor_service.create(session, payload, actor_id=user.id)
    return VisitorRead.model_validate(visitor)


@router.get("/{visitor_id}", response_model=VisitorRead, summary="Get a visitor")
async def get_visitor(
    visitor_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> VisitorRead:
    visitor = await visitor_service.get(session, visitor_id)
    enforce_compound(user, visitor.compound_id)
    if not is_manager(user):
        profile = await _resident_scope(session, user)
        if visitor.host_unit_id != profile.unit_id:
            raise PermissionDeniedError("You can only view visitors of your own unit")
    return VisitorRead.model_validate(visitor)


@router.patch("/{visitor_id}", response_model=VisitorRead, summary="Update a visitor")
async def update_visitor(
    visitor_id: uuid.UUID,
    payload: VisitorUpdate,
    session: SessionDep,
    manager: ManagerUser,
) -> VisitorRead:
    visitor = await visitor_service.get(session, visitor_id)
    enforce_compound(manager, visitor.compound_id)
    return VisitorRead.model_validate(await visitor_service.update(session, visitor_id, payload))


@router.delete("/{visitor_id}", response_model=Message, summary="Delete a visitor")
async def delete_visitor(
    visitor_id: uuid.UUID, session: SessionDep, manager: ManagerUser
) -> Message:
    visitor = await visitor_service.get(session, visitor_id)
    enforce_compound(manager, visitor.compound_id)
    await visitor_service.delete(session, visitor_id)
    return Message(message=f"Visitor {visitor.full_name} deleted")


async def _transition(
    session, manager, visitor_id: uuid.UUID, status_value: VisitorStatus
) -> VisitorRead:
    visitor = await visitor_service.get(session, visitor_id)
    enforce_compound(manager, visitor.compound_id)
    updated = await visitor_service.set_status(session, visitor_id, status_value)
    return VisitorRead.model_validate(updated)


@router.post("/{visitor_id}/approve", response_model=VisitorRead, summary="Approve a visitor")
async def approve_visitor(
    visitor_id: uuid.UUID, session: SessionDep, manager: ManagerUser
) -> VisitorRead:
    return await _transition(session, manager, visitor_id, VisitorStatus.APPROVED)


@router.post("/{visitor_id}/reject", response_model=VisitorRead, summary="Reject a visitor")
async def reject_visitor(
    visitor_id: uuid.UUID, session: SessionDep, manager: ManagerUser
) -> VisitorRead:
    return await _transition(session, manager, visitor_id, VisitorStatus.REJECTED)


@router.post("/{visitor_id}/check-in", response_model=VisitorRead, summary="Check a visitor in")
async def check_in_visitor(
    visitor_id: uuid.UUID, session: SessionDep, manager: ManagerUser
) -> VisitorRead:
    return await _transition(session, manager, visitor_id, VisitorStatus.CHECKED_IN)


@router.post("/{visitor_id}/check-out", response_model=VisitorRead, summary="Check a visitor out")
async def check_out_visitor(
    visitor_id: uuid.UUID, session: SessionDep, manager: ManagerUser
) -> VisitorRead:
    return await _transition(session, manager, visitor_id, VisitorStatus.CHECKED_OUT)


@router.post("/{visitor_id}/photo", response_model=VisitorRead, summary="Upload a visitor photo")
async def upload_photo(
    visitor_id: uuid.UUID,
    session: SessionDep,
    manager: ManagerUser,
    file: UploadFile = File(..., description="JPEG or PNG image"),
) -> VisitorRead:
    visitor = await visitor_service.get(session, visitor_id)
    enforce_compound(manager, visitor.compound_id)
    if not file.content_type or not file.content_type.startswith("image/"):
        raise BadRequestError("Only image uploads are supported")
    data = await file.read()
    return VisitorRead.model_validate(await visitor_service.update_photo(session, visitor_id, data))
