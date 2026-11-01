"""Access log queries, exports, manual overrides and manual entries."""

from __future__ import annotations

import csv
import io
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from openpyxl import Workbook
from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_event
from app.core.exceptions import BadRequestError, NotFoundError, PermissionDeniedError
from app.core.logging import get_logger
from app.cv.gate_controller import ReasonCode, get_gate_controller
from app.cv.utils import format_plate, normalize_plate, plate_variants
from app.models.access import AccessLog, DetectionEvent
from app.models.compound import Compound, Gate
from app.models.enums import (
    AccessDecision,
    AccessDirection,
    AccessMethod,
    DetectionType,
)
from app.models.people import Permit, Visitor
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.access import ManualEntryRequest, ManualOverrideRequest
from app.schemas.common import Page
from app.services.pagination import PageParams, apply_sort, build_page, count_rows

logger = get_logger(__name__)


@dataclass(slots=True)
class LogFilters:
    """Filters accepted by the access log and detection queries."""

    compound_id: uuid.UUID | None = None
    gate_id: uuid.UUID | None = None
    decision: AccessDecision | None = None
    direction: AccessDirection | None = None
    method: AccessMethod | None = None
    plate: str | None = None
    search: str | None = None
    resident_id: uuid.UUID | None = None
    visitor_id: uuid.UUID | None = None
    vehicle_id: uuid.UUID | None = None
    start: datetime | None = None
    end: datetime | None = None
    overridden: bool | None = None
    requires_review: bool = False
    resident_scope_id: uuid.UUID | None = None
    unit_scope_id: uuid.UUID | None = None


def _log_columns() -> dict[str, Any]:
    return {
        "occurred_at": AccessLog.occurred_at,
        "decision": AccessLog.decision,
        "plate_number": AccessLog.plate_number,
        "created_at": AccessLog.created_at,
    }


class AccessService:
    """Read model for the audit trail plus officer actions."""

    def _apply_filters(self, stmt: Select[tuple[AccessLog]], filters: LogFilters) -> Select[tuple[AccessLog]]:
        if filters.compound_id is not None:
            stmt = stmt.where(AccessLog.compound_id == filters.compound_id)
        if filters.gate_id is not None:
            stmt = stmt.where(AccessLog.gate_id == filters.gate_id)
        if filters.decision is not None:
            stmt = stmt.where(AccessLog.decision == filters.decision)
        if filters.direction is not None:
            stmt = stmt.where(AccessLog.direction == filters.direction)
        if filters.method is not None:
            stmt = stmt.where(AccessLog.access_method == filters.method)
        if filters.requires_review:
            stmt = stmt.where(AccessLog.decision == AccessDecision.REVIEW)
        if filters.plate:
            normalized = normalize_plate(filters.plate)
            stmt = stmt.where(
                or_(
                    AccessLog.plate_normalized.ilike(f"%{normalized}%"),
                    AccessLog.plate_number.ilike(f"%{filters.plate.strip()}%"),
                )
            )
        if filters.resident_id is not None:
            stmt = stmt.where(AccessLog.resident_id == filters.resident_id)
        if filters.visitor_id is not None:
            stmt = stmt.where(AccessLog.visitor_id == filters.visitor_id)
        if filters.vehicle_id is not None:
            stmt = stmt.where(AccessLog.vehicle_id == filters.vehicle_id)
        if filters.start is not None:
            stmt = stmt.where(AccessLog.occurred_at >= filters.start)
        if filters.end is not None:
            stmt = stmt.where(AccessLog.occurred_at <= filters.end)
        if filters.overridden is not None:
            stmt = stmt.where(AccessLog.is_overridden.is_(filters.overridden))
        if filters.search:
            term = f"%{filters.search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    AccessLog.plate_number.ilike(term),
                    AccessLog.reason.ilike(term),
                    AccessLog.reason_code.ilike(term),
                    AccessLog.notes.ilike(term),
                )
            )
        if filters.resident_scope_id is not None:
            stmt = stmt.where(
                or_(
                    AccessLog.resident_id == filters.resident_scope_id,
                    AccessLog.visitor_id.in_(
                        select(Visitor.id).where(Visitor.host_resident_id == filters.resident_scope_id)
                    ),
                )
            )
        if filters.unit_scope_id is not None:
            stmt = stmt.where(
                AccessLog.visitor_id.in_(
                    select(Visitor.id).where(Visitor.host_unit_id == filters.unit_scope_id)
                )
            )
        return stmt

    async def list_logs(
        self, session: AsyncSession, params: PageParams, filters: LogFilters
    ) -> Page[AccessLog]:
        stmt = self._apply_filters(select(AccessLog), filters)
        total = await count_rows(session, stmt)
        column = _log_columns().get(params.sort_by, AccessLog.occurred_at)
        stmt = apply_sort(stmt, column, params.sort_dir).offset(params.offset).limit(params.page_size)
        items = list((await session.execute(stmt)).scalars().unique().all())
        return build_page(items, total, params)

    async def get_log(self, session: AsyncSession, log_id: uuid.UUID) -> AccessLog:
        log = await session.get(AccessLog, log_id)
        if log is None:
            raise NotFoundError("Access log not found", code="access_log_not_found")
        return log

    async def list_detections(
        self,
        session: AsyncSession,
        params: PageParams,
        filters: LogFilters,
        *,
        event_type: DetectionType | None = None,
    ) -> Page[DetectionEvent]:
        stmt = select(DetectionEvent)
        if filters.compound_id is not None:
            stmt = stmt.where(DetectionEvent.compound_id == filters.compound_id)
        if filters.gate_id is not None:
            stmt = stmt.where(DetectionEvent.gate_id == filters.gate_id)
        if filters.decision is not None:
            stmt = stmt.where(DetectionEvent.decision == filters.decision)
        if filters.plate:
            normalized = normalize_plate(filters.plate)
            stmt = stmt.where(DetectionEvent.plate_text.ilike(f"%{normalized}%"))
        if filters.start is not None:
            stmt = stmt.where(DetectionEvent.occurred_at >= filters.start)
        if filters.end is not None:
            stmt = stmt.where(DetectionEvent.occurred_at <= filters.end)
        if event_type is not None:
            stmt = stmt.where(DetectionEvent.event_type == event_type)
        if filters.search:
            term = f"%{filters.search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    DetectionEvent.plate_text.ilike(term),
                    DetectionEvent.decision_reason.ilike(term),
                )
            )
        total = await count_rows(session, stmt)
        stmt = stmt.order_by(DetectionEvent.occurred_at.desc()).offset(params.offset).limit(
            params.page_size
        )
        items = list((await session.execute(stmt)).scalars().unique().all())
        return build_page(items, total, params)

    async def get_detection(self, session: AsyncSession, detection_id: uuid.UUID) -> DetectionEvent:
        detection = await session.get(DetectionEvent, detection_id)
        if detection is None:
            raise NotFoundError("Detection event not found", code="detection_not_found")
        return detection

    async def override(
        self,
        session: AsyncSession,
        log_id: uuid.UUID,
        payload: ManualOverrideRequest,
        *,
        actor: User,
    ) -> AccessLog:
        log = await self.get_log(session, log_id)
        gate = await session.get(Gate, log.gate_id)
        if gate is None:
            raise NotFoundError("Gate not found")
        if actor.compound_id is not None and actor.compound_id != gate.compound_id:
            raise PermissionDeniedError("You cannot override logs from another compound")
        accepted = False
        if payload.open_gate or payload.decision == AccessDecision.ALLOW:
            compound = await session.get(Compound, gate.compound_id)
            command = await get_gate_controller().execute(
                gate, compound, "open", f"Manual override: {payload.reason}", actor=actor.email
            )
            accepted = command.accepted
        log.decision = payload.decision
        log.access_method = AccessMethod.MANUAL
        log.is_overridden = True
        log.override_by_id = actor.id
        log.override_reason = payload.reason
        log.overridden_at = datetime.now(UTC)
        log.gate_opened = accepted
        if payload.notes:
            log.notes = payload.notes
        await session.commit()
        await session.refresh(log)
        await publish_event(
            "access.override",
            {
                "access_log_id": str(log.id),
                "decision": log.decision.value,
                "reason": payload.reason,
                "officer": actor.full_name,
                "gate_opened": accepted,
                "occurred_at": log.occurred_at.isoformat(),
            },
        )
        logger.info(
            "Access override: log=%s decision=%s by=%s", log.id, log.decision.value, actor.email
        )
        return log

    async def manual_entry(
        self, session: AsyncSession, payload: ManualEntryRequest, *, actor: User
    ) -> AccessLog:
        gate = await session.get(Gate, payload.gate_id)
        if gate is None:
            raise NotFoundError("Gate not found", code="gate_not_found")
        if actor.compound_id is not None and actor.compound_id != gate.compound_id:
            raise PermissionDeniedError("You cannot log access for another compound")
        compound = await session.get(Compound, gate.compound_id)
        normalized = normalize_plate(payload.plate_number) if payload.plate_number else None
        lookup_keys = plate_variants(payload.plate_number)
        vehicle = None
        if lookup_keys:
            vehicle = await session.scalar(
                select(Vehicle).where(
                    Vehicle.compound_id == gate.compound_id,
                    Vehicle.plate_normalized.in_(lookup_keys),
                )
            )
        visitor = None
        permit = None
        if lookup_keys:
            permit = await session.scalar(
                select(Permit)
                .join(Vehicle, Permit.vehicle_id == Vehicle.id)
                .where(
                    Permit.compound_id == gate.compound_id,
                    Vehicle.plate_normalized.in_(lookup_keys),
                )
                .order_by(Permit.end_at.desc())
            )
            if permit is not None:
                visitor = permit.visitor

        accepted = False
        if payload.open_gate and payload.decision == AccessDecision.ALLOW:
            command = await get_gate_controller().execute(
                gate, compound, "open", f"Manual entry: {payload.reason}", actor=actor.email
            )
            accepted = command.accepted

        log = AccessLog(
            compound_id=gate.compound_id,
            gate_id=gate.id,
            direction=payload.direction,
            occurred_at=datetime.now(UTC),
            decision=payload.decision,
            reason_code=ReasonCode.MANUAL_OVERRIDE,
            reason=payload.reason,
            access_method=AccessMethod.MANUAL,
            plate_number=format_plate(payload.plate_number) if payload.plate_number else None,
            plate_normalized=normalized,
            vehicle_id=vehicle.id if vehicle else None,
            resident_id=vehicle.resident_id if vehicle else None,
            visitor_id=visitor.id if visitor else None,
            permit_id=permit.id if permit else None,
            is_overridden=True,
            override_by_id=actor.id,
            override_reason=payload.reason,
            overridden_at=datetime.now(UTC),
            gate_opened=accepted,
            notes=payload.notes,
        )
        session.add(log)
        await session.commit()
        await session.refresh(log)
        await publish_event(
            "detection.created",
            {
                "access_log_id": str(log.id),
                "gate_id": str(gate.id),
                "gate_name": gate.name,
                "decision": log.decision.value,
                "reason": log.reason,
                "plate_text": log.plate_number,
                "method": "manual",
                "occurred_at": log.occurred_at.isoformat(),
                "officer": actor.full_name,
            },
        )
        return log

    async def export_logs(
        self, session: AsyncSession, filters: LogFilters, fmt: str = "csv"
    ) -> tuple[bytes, str, str]:
        """Export filtered logs as CSV or XLSX; returns bytes, filename, mime type."""
        stmt = self._apply_filters(select(AccessLog), filters)
        stmt = stmt.order_by(AccessLog.occurred_at.desc()).limit(50_000)
        logs = list((await session.execute(stmt)).scalars().unique().all())
        headers = [
            "Occurred At",
            "Gate",
            "Direction",
            "Decision",
            "Reason Code",
            "Reason",
            "Method",
            "Plate",
            "Resident",
            "Visitor",
            "Permit",
            "Plate Confidence",
            "Face Similarity",
            "Overridden",
            "Override Reason",
            "Notes",
        ]
        rows = [
            [
                log.occurred_at.isoformat(),
                log.gate.name if log.gate else "",
                log.direction.value,
                log.decision.value,
                log.reason_code,
                log.reason,
                log.access_method.value,
                log.plate_number or "",
                log.resident.full_name if log.resident else "",
                log.visitor.full_name if log.visitor else "",
                log.permit.permit_code if log.permit else "",
                round(log.plate_confidence, 3) if log.plate_confidence is not None else "",
                round(log.face_similarity, 3) if log.face_similarity is not None else "",
                "yes" if log.is_overridden else "no",
                log.override_reason or "",
                log.notes or "",
            ]
            for log in logs
        ]
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        if fmt.lower() == "xlsx":
            workbook = Workbook(write_only=True)
            sheet = workbook.create_sheet("Access Logs")
            sheet.append(headers)
            for row in rows:
                sheet.append(row)
            buffer = io.BytesIO()
            workbook.save(buffer)
            return (
                buffer.getvalue(),
                f"gatevision-access-logs-{stamp}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        if fmt.lower() != "csv":
            raise BadRequestError("Unsupported export format; use csv or xlsx")
        text_buffer = io.StringIO()
        writer = csv.writer(text_buffer)
        writer.writerow(headers)
        writer.writerows(rows)
        return (
            text_buffer.getvalue().encode("utf-8-sig"),
            f"gatevision-access-logs-{stamp}.csv",
            "text/csv; charset=utf-8",
        )


access_service = AccessService()
