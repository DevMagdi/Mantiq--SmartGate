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
from app.core.logging import get_logger
from app.models.enums import UnitStatus, UnitType
from app.schemas.common import Message, Page
from app.schemas.compound import (
    CompoundCreate,
    CompoundRead,
    CompoundSettingsRead,
    CompoundSettingsUpdate,
    CompoundUpdate,
    UnitCreate,
    UnitRead,
    UnitUpdate,
)
from app.services.compound_policy import CompoundPolicy, mask_settings
from app.services.compound_service import compound_service, unit_service
from app.services.permissions import compound_scope, enforce_compound, is_admin

router = APIRouter(prefix="/compounds", tags=["Compounds & Units"])

logger = get_logger(__name__)


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


@router.get(
    "/{compound_id}/settings",
    response_model=CompoundSettingsRead,
    summary="Get the effective compound policy",
)
async def get_settings(
    compound_id: uuid.UUID, session: SessionDep, manager: ManagerUser
) -> CompoundSettingsRead:
    """Return the raw document, the masked effective policy and the defaults."""
    compound = await compound_service.get(session, compound_id)
    enforce_compound(manager, compound.id)
    policy = CompoundPolicy.from_settings(compound.settings)
    return CompoundSettingsRead(
        compound_id=compound.id,
        raw=dict(compound.settings or {}),
        effective=policy.to_dict(mask_secrets=True),
        defaults=CompoundPolicy().to_dict(mask_secrets=True),
    )


@router.patch(
    "/{compound_id}/settings",
    response_model=CompoundSettingsRead,
    summary="Update thresholds and barrier configuration",
)
async def update_settings(
    compound_id: uuid.UUID,
    payload: CompoundSettingsUpdate,
    session: SessionDep,
    admin: AdminUser,
) -> CompoundSettingsRead:
    """Deep-merge validated policy sections into the compound document."""
    enforce_compound(admin, compound_id)
    patch = payload.model_dump(exclude_unset=True, exclude_none=True)
    compound = await compound_service.update_settings(session, compound_id, patch)
    policy = CompoundPolicy.from_settings(compound.settings)
    await _refresh_runtime_policy()
    logger.info("Compound %s policy updated by %s", compound.code, admin.email)
    return CompoundSettingsRead(
        compound_id=compound.id,
        raw=mask_settings(compound.settings),
        effective=policy.to_dict(mask_secrets=True),
        defaults=CompoundPolicy().to_dict(mask_secrets=True),
    )


async def _refresh_runtime_policy() -> None:
    """Apply new thresholds to running camera workers when present."""
    from app.cv.manager import get_camera_manager

    manager = get_camera_manager()
    if manager is not None:
        try:
            await manager.refresh_policies()
        except Exception:  # pragma: no cover - never fail the API on supervisor issues
            logger.exception("Could not refresh camera policies")


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
        unit_type=unit_type,
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
