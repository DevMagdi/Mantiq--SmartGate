"""Access log, detection and officer action endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Query, Response, status

from app.api.deps import (
    CompoundScope,
    CurrentUser,
    ManagerUser,
    PaginationDep,
    SessionDep,
)
from app.core.exceptions import PermissionDeniedError
from app.models.enums import (
    AccessDecision,
    AccessDirection,
    AccessMethod,
    DetectionType,
)
from app.schemas.access import (
    AccessLogRead,
    DetectionEventRead,
    ManualEntryRequest,
    ManualOverrideRequest,
)
from app.schemas.common import Page
from app.services.access_service import LogFilters, access_service
from app.services.permissions import compound_scope, enforce_compound, is_manager
from app.services.resident_service import resident_service
from app.services.gate_service import gate_service

router = APIRouter(tags=["Access Control"])


async def _resolve_filters(
    session,
    user,
    compound_id: uuid.UUID | None,
    *,
    gate_id: uuid.UUID | None = None,
    decision: AccessDecision | None = None,
    direction: AccessDirection | None = None,
    method: AccessMethod | None = None,
    plate: str | None = None,
    search: str | None = None,
    resident_id: uuid.UUID | None = None,
    visitor_id: uuid.UUID | None = None,
    vehicle_id: uuid.UUID | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    overridden: bool | None = None,
    requires_review: bool = False,
) -> LogFilters:
    filters = LogFilters(
        compound_id=compound_scope(user, compound_id),
        gate_id=gate_id,
        decision=decision,
        direction=direction,
        method=method,
        plate=plate,
        search=search,
        resident_id=resident_id,
        visitor_id=visitor_id,
        vehicle_id=vehicle_id,
        start=start,
        end=end,
        overridden=overridden,
        requires_review=requires_review,
    )
    if not is_manager(user):
        profile = await resident_service.get_by_user(session, user.id)
        if profile is None:
            raise PermissionDeniedError("No resident profile is linked to this account")
        filters.compound_id = profile.compound_id
        filters.resident_scope_id = profile.id
    return filters


@router.get("/access-logs", response_model=Page[AccessLogRead], summary="Search access logs")
async def list_access_logs(
    session: SessionDep,
    user: CurrentUser,
    pagination: PaginationDep,
    compound_id: CompoundScope,
    gate_id: uuid.UUID | None = Query(default=None),
    decision: AccessDecision | None = Query(default=None),
    direction: AccessDirection | None = Query(default=None),
    method: AccessMethod | None = Query(default=None),
    plate: str | None = Query(default=None, max_length=20),
    search: str | None = Query(default=None, max_length=120),
    resident_id: uuid.UUID | None = Query(default=None),
    visitor_id: uuid.UUID | None = Query(default=None),
    vehicle_id: uuid.UUID | None = Query(default=None),
    start: datetime | None = Query(default=None, description="ISO 8601 start timestamp"),
    end: datetime | None = Query(default=None, description="ISO 8601 end timestamp"),
    overridden: bool | None = Query(default=None),
    requires_review: bool = Query(default=False),
) -> Page[AccessLogRead]:
    filters = await _resolve_filters(
        session,
        user,
        compound_id,
        gate_id=gate_id,
        decision=decision,
        direction=direction,
        method=method,
        plate=plate,
        search=search,
        resident_id=resident_id,
        visitor_id=visitor_id,
        vehicle_id=vehicle_id,
        start=start,
        end=end,
        overridden=overridden,
        requires_review=requires_review,
    )
    page = await access_service.list_logs(session, pagination.to_params(), filters)
    return Page[AccessLogRead].create(
        [AccessLogRead.model_validate(item) for item in page.items],
        page.total,
        page.page,
        page.page_size,
    )


@router.get(
    "/access-logs/export",
    summary="Export access logs (CSV or XLSX)",
    responses={200: {"content": {"text/csv": {}, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}}}},
)
async def export_access_logs(
    session: SessionDep,
    user: CurrentUser,
    compound_id: CompoundScope,
    fmt: str = Query(default="csv", alias="format", pattern="^(csv|xlsx)$"),
    gate_id: uuid.UUID | None = Query(default=None),
    decision: AccessDecision | None = Query(default=None),
    direction: AccessDirection | None = Query(default=None),
    plate: str | None = Query(default=None, max_length=20),
    search: str | None = Query(default=None, max_length=120),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    overridden: bool | None = Query(default=None),
) -> Response:
    filters = await _resolve_filters(
        session,
        user,
        compound_id,
        gate_id=gate_id,
        decision=decision,
        direction=direction,
        plate=plate,
        search=search,
        start=start,
        end=end,
        overridden=overridden,
    )
    content, filename, media_type = await access_service.export_logs(session, filters, fmt)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/access-logs/{log_id}", response_model=AccessLogRead, summary="Get an access log")
async def get_access_log(
    log_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> AccessLogRead:
    log = await access_service.get_log(session, log_id)
    enforce_compound(user, log.compound_id)
    if not is_manager(user):
        profile = await resident_service.get_by_user(session, user.id)
        if profile is None:
            raise PermissionDeniedError("No resident profile is linked to this account")
        if log.resident_id != profile.id and (
            log.visitor is None or log.visitor.host_unit_id != profile.unit_id
        ):
            raise PermissionDeniedError("You can only view your own access records")
    return AccessLogRead.model_validate(log)


@router.post(
    "/access-logs/{log_id}/override",
    response_model=AccessLogRead,
    summary="Override an access decision",
)
async def override_access_log(
    log_id: uuid.UUID,
    payload: ManualOverrideRequest,
    session: SessionDep,
    manager: ManagerUser,
) -> AccessLogRead:
    log = await access_service.override(session, log_id, payload, actor=manager)
    return AccessLogRead.model_validate(log)


@router.post(
    "/access-logs/manual",
    response_model=AccessLogRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record a manual gate operation",
)
async def manual_entry(
    payload: ManualEntryRequest, session: SessionDep, manager: ManagerUser
) -> AccessLogRead:
    gate = await gate_service.get(session, payload.gate_id)
    enforce_compound(manager, gate.compound_id)
    log = await access_service.manual_entry(session, payload, actor=manager)
    return AccessLogRead.model_validate(log)


@router.get("/detections", response_model=Page[DetectionEventRead], summary="List detections")
async def list_detections(
    session: SessionDep,
    manager: ManagerUser,
    pagination: PaginationDep,
    compound_id: CompoundScope,
    gate_id: uuid.UUID | None = Query(default=None),
    decision: AccessDecision | None = Query(default=None),
    event_type: DetectionType | None = Query(default=None),
    plate: str | None = Query(default=None, max_length=20),
    search: str | None = Query(default=None, max_length=120),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
) -> Page[DetectionEventRead]:
    filters = LogFilters(
        compound_id=compound_id,
        gate_id=gate_id,
        decision=decision,
        plate=plate,
        search=search,
        start=start,
        end=end,
    )
    page = await access_service.list_detections(
        session, pagination.to_params(), filters, event_type=event_type
    )
    return Page[DetectionEventRead].create(
        [DetectionEventRead.model_validate(item) for item in page.items],
        page.total,
        page.page,
        page.page_size,
    )


@router.get(
    "/detections/{detection_id}",
    response_model=DetectionEventRead,
    summary="Get a detection event",
)
async def get_detection(
    detection_id: uuid.UUID, session: SessionDep, manager: ManagerUser
) -> DetectionEventRead:
    detection = await access_service.get_detection(session, detection_id)
    enforce_compound(manager, detection.compound_id)
    return DetectionEventRead.model_validate(detection)
