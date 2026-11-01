"""Blacklist endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CompoundScope, ManagerUser, PaginationDep, SessionDep
from app.core.exceptions import PermissionDeniedError
from app.models.enums import BlacklistEntryType
from app.schemas.common import Message, Page
from app.schemas.security import BlacklistCreate, BlacklistRead, BlacklistUpdate
from app.services.blacklist_service import blacklist_service
from app.services.permissions import enforce_compound

router = APIRouter(prefix="/blacklist", tags=["Blacklist"])


@router.get("", response_model=Page[BlacklistRead], summary="List blacklist entries")
async def list_entries(
    session: SessionDep,
    manager: ManagerUser,
    pagination: PaginationDep,
    compound_id: CompoundScope,
    entry_type: BlacklistEntryType | None = Query(default=None),
    is_active: bool | None = Query(default=None, description="Filter by activation state; omit for all"),
    search: str | None = Query(default=None, max_length=120),
) -> Page[BlacklistRead]:
    page = await blacklist_service.list(
        session,
        pagination.to_params(),
        compound_id=compound_id,
        entry_type=entry_type,
        is_active=is_active,
        search=search,
    )
    return Page[BlacklistRead].create(
        [BlacklistRead.model_validate(item) for item in page.items],
        page.total,
        page.page,
        page.page_size,
    )


@router.post(
    "",
    response_model=BlacklistRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a blacklist entry",
)
async def create_entry(
    payload: BlacklistCreate, session: SessionDep, manager: ManagerUser
) -> BlacklistRead:
    enforce_compound(manager, payload.compound_id)
    entry = await blacklist_service.create(session, payload, actor_id=manager.id)
    return BlacklistRead.model_validate(entry)


@router.get("/{entry_id}", response_model=BlacklistRead, summary="Get a blacklist entry")
async def get_entry(
    entry_id: uuid.UUID, session: SessionDep, manager: ManagerUser
) -> BlacklistRead:
    entry = await blacklist_service.get(session, entry_id)
    if manager.compound_id is not None and manager.compound_id != entry.compound_id:
        raise PermissionDeniedError("You cannot access another compound")
    return BlacklistRead.model_validate(entry)


@router.patch("/{entry_id}", response_model=BlacklistRead, summary="Update a blacklist entry")
async def update_entry(
    entry_id: uuid.UUID, payload: BlacklistUpdate, session: SessionDep, manager: ManagerUser
) -> BlacklistRead:
    entry = await blacklist_service.get(session, entry_id)
    enforce_compound(manager, entry.compound_id)
    return BlacklistRead.model_validate(
        await blacklist_service.update(session, entry_id, payload)
    )


@router.delete("/{entry_id}", response_model=Message, summary="Delete a blacklist entry")
async def delete_entry(
    entry_id: uuid.UUID, session: SessionDep, manager: ManagerUser
) -> Message:
    entry = await blacklist_service.get(session, entry_id)
    enforce_compound(manager, entry.compound_id)
    await blacklist_service.delete(session, entry_id)
    return Message(message="Blacklist entry deleted")
