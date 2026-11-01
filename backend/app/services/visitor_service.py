"""Visitor and temporary permit management."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models.base import as_utc
from app.models.compound import Unit
from app.models.enums import PermitStatus, VisitorStatus
from app.models.people import Permit, Resident, Visitor
from app.models.vehicle import Vehicle
from app.schemas.common import Page
from app.schemas.people import PermitCreate, PermitUpdate, VisitorCreate, VisitorUpdate
from app.services.pagination import PageParams, apply_sort, build_page, count_rows
from app.cv.snapshots import SnapshotStore
from app.services.face_service import decode_image
from app.services.vehicle_service import vehicle_service


def _utcnow() -> datetime:
    return datetime.now(UTC)


class VisitorService:
    """Visitor registry with approval and presence tracking."""

    def __init__(self) -> None:
        self.store = SnapshotStore()

    async def get(self, session: AsyncSession, visitor_id: uuid.UUID) -> Visitor:
        visitor = await session.get(Visitor, visitor_id)
        if visitor is None:
            raise NotFoundError("Visitor not found", code="visitor_not_found")
        return visitor

    async def list(
        self,
        session: AsyncSession,
        params: PageParams,
        *,
        compound_id: uuid.UUID | None,
        status: VisitorStatus | None = None,
        host_unit_id: uuid.UUID | None = None,
        host_resident_id: uuid.UUID | None = None,
        active_only: bool = False,
        search: str | None = None,
    ) -> Page[Visitor]:
        stmt = select(Visitor)
        if compound_id is not None:
            stmt = stmt.where(Visitor.compound_id == compound_id)
        if status is not None:
            stmt = stmt.where(Visitor.status == status)
        if host_unit_id is not None:
            stmt = stmt.where(Visitor.host_unit_id == host_unit_id)
        if host_resident_id is not None:
            stmt = stmt.where(Visitor.host_resident_id == host_resident_id)
        if active_only:
            stmt = stmt.where(
                Visitor.status.in_(
                    [VisitorStatus.PENDING, VisitorStatus.APPROVED, VisitorStatus.CHECKED_IN]
                )
            )
        if search:
            term = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    Visitor.full_name.ilike(term),
                    Visitor.phone.ilike(term),
                    Visitor.company.ilike(term),
                    Visitor.national_id.ilike(term),
                )
            )
        total = await count_rows(session, stmt)
        columns = {
            "full_name": Visitor.full_name,
            "status": Visitor.status,
            "expected_arrival": Visitor.expected_arrival,
        }
        stmt = apply_sort(stmt, columns.get(params.sort_by, Visitor.created_at), params.sort_dir)
        stmt = stmt.offset(params.offset).limit(params.page_size)
        visitors = list((await session.execute(stmt)).scalars().unique().all())
        await self._attach_counts(session, visitors)
        return build_page(visitors, total, params)

    async def _attach_counts(self, session: AsyncSession, visitors: list[Visitor]) -> None:
        if not visitors:
            return
        ids = [visitor.id for visitor in visitors]
        rows = (
            await session.execute(
                select(Permit.visitor_id, func.count(Permit.id))
                .where(
                    Permit.visitor_id.in_(ids),
                    Permit.status.in_([PermitStatus.ACTIVE, PermitStatus.PENDING]),
                )
                .group_by(Permit.visitor_id)
            )
        ).all()
        counts = {row[0]: int(row[1]) for row in rows}
        for visitor in visitors:
            visitor.active_permit_count = counts.get(visitor.id, 0)  # type: ignore[attr-defined]

    async def create(
        self, session: AsyncSession, payload: VisitorCreate, *, actor_id: uuid.UUID | None
    ) -> Visitor:
        unit = await session.get(Unit, payload.host_unit_id)
        if unit is None or unit.compound_id != payload.compound_id:
            raise BadRequestError("The host unit does not belong to this compound")
        if payload.host_resident_id is not None:
            resident = await session.get(Resident, payload.host_resident_id)
            if resident is None or resident.compound_id != payload.compound_id:
                raise BadRequestError("The host resident does not belong to this compound")
        visitor = Visitor(
            **payload.model_dump(),
            status=VisitorStatus.PENDING,
            created_by_id=actor_id,
        )
        session.add(visitor)
        await session.commit()
        await session.refresh(visitor)
        return visitor

    async def update(
        self, session: AsyncSession, visitor_id: uuid.UUID, payload: VisitorUpdate
    ) -> Visitor:
        visitor = await self.get(session, visitor_id)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(visitor, field, value)
        await session.commit()
        await session.refresh(visitor)
        return visitor

    async def set_status(
        self,
        session: AsyncSession,
        visitor_id: uuid.UUID,
        status: VisitorStatus,
    ) -> Visitor:
        visitor = await self.get(session, visitor_id)
        if visitor.status in {VisitorStatus.CHECKED_OUT, VisitorStatus.CANCELLED} and status in {
            VisitorStatus.APPROVED,
            VisitorStatus.CHECKED_IN,
        }:
            raise BadRequestError("This visitor record is closed and cannot be reopened")
        visitor.status = status
        if status == VisitorStatus.CHECKED_IN and visitor.actual_arrival is None:
            visitor.actual_arrival = _utcnow()
        if status == VisitorStatus.CHECKED_OUT:
            visitor.actual_departure = _utcnow()
        await session.commit()
        await session.refresh(visitor)
        return visitor

    async def update_photo(
        self, session: AsyncSession, visitor_id: uuid.UUID, data: bytes
    ) -> Visitor:
        """Validate and persist a visitor photo."""
        image = decode_image(data)
        visitor = await self.get(session, visitor_id)
        visitor.photo_url = self.store.save_image(image, "visitor-photos")
        await session.commit()
        await session.refresh(visitor)
        return visitor

    async def delete(self, session: AsyncSession, visitor_id: uuid.UUID) -> None:
        visitor = await self.get(session, visitor_id)
        await session.delete(visitor)
        await session.commit()


class PermitService:
    """Temporary permits with expiry, entry limits and revocation."""

    async def get(self, session: AsyncSession, permit_id: uuid.UUID) -> Permit:
        permit = await session.get(Permit, permit_id)
        if permit is None:
            raise NotFoundError("Permit not found", code="permit_not_found")
        return permit

    async def get_by_code(self, session: AsyncSession, code: str) -> Permit | None:
        return await session.scalar(select(Permit).where(Permit.permit_code == code))

    def _generate_code(self) -> str:
        return f"PMT-{datetime.now(UTC).strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"

    def _status_for_window(self, start_at: datetime, end_at: datetime) -> PermitStatus:
        now = _utcnow()
        if as_utc(end_at) < now:
            return PermitStatus.EXPIRED
        if as_utc(start_at) > now:
            return PermitStatus.PENDING
        return PermitStatus.ACTIVE

    async def list(
        self,
        session: AsyncSession,
        params: PageParams,
        *,
        compound_id: uuid.UUID | None,
        status: PermitStatus | None = None,
        visitor_id: uuid.UUID | None = None,
        host_unit_id: uuid.UUID | None = None,
        active_only: bool = False,
        search: str | None = None,
    ) -> Page[Permit]:
        stmt = select(Permit)
        if compound_id is not None:
            stmt = stmt.where(Permit.compound_id == compound_id)
        if status is not None:
            stmt = stmt.where(Permit.status == status)
        if visitor_id is not None:
            stmt = stmt.where(Permit.visitor_id == visitor_id)
        if host_unit_id is not None:
            stmt = stmt.where(Permit.host_unit_id == host_unit_id)
        now = _utcnow()
        if active_only:
            stmt = stmt.where(
                Permit.status == PermitStatus.ACTIVE,
                Permit.start_at <= now,
                Permit.end_at >= now,
                Permit.entries_used < Permit.max_entries,
            )
        if search:
            term = f"%{search.strip().lower()}%"
            stmt = stmt.join(Visitor, Permit.visitor_id == Visitor.id).where(
                or_(
                    Permit.permit_code.ilike(term),
                    Visitor.full_name.ilike(term),
                    Visitor.phone.ilike(term),
                )
            )
        total = await count_rows(session, stmt)
        columns = {"end_at": Permit.end_at, "status": Permit.status, "created_at": Permit.created_at}
        stmt = apply_sort(stmt, columns.get(params.sort_by, Permit.created_at), params.sort_dir)
        stmt = stmt.offset(params.offset).limit(params.page_size)
        items = list((await session.execute(stmt)).scalars().unique().all())
        return build_page(items, total, params)

    async def create(
        self,
        session: AsyncSession,
        payload: PermitCreate,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> Permit:
        visitor = await session.get(Visitor, payload.visitor_id)
        if visitor is None:
            raise BadRequestError("The visitor does not exist")
        if visitor.status in {VisitorStatus.REJECTED, VisitorStatus.CANCELLED}:
            raise BadRequestError("A permit cannot be issued for a rejected or cancelled visitor")
        unit = await session.get(Unit, payload.host_unit_id)
        if unit is None or unit.compound_id != visitor.compound_id:
            raise BadRequestError("The host unit does not belong to this compound")

        vehicle: Vehicle | None = None
        if payload.vehicle_id is not None:
            vehicle = await session.get(Vehicle, payload.vehicle_id)
            if vehicle is None or vehicle.compound_id != visitor.compound_id:
                raise BadRequestError("The vehicle does not belong to this compound")
        elif payload.vehicle_plate:
            vehicle = await vehicle_service.ensure_visitor_vehicle(
                session, visitor.compound_id, payload.vehicle_plate
            )

        code = self._generate_code()
        while await self.get_by_code(session, code) is not None:
            code = self._generate_code()

        data = payload.model_dump(exclude={"vehicle_plate", "vehicle_id"})
        permit = Permit(
            **data,
            compound_id=visitor.compound_id,
            vehicle_id=vehicle.id if vehicle else None,
            permit_code=code,
            status=self._status_for_window(payload.start_at, payload.end_at),
            issued_by_id=actor_id,
        )
        session.add(permit)
        if visitor.status == VisitorStatus.PENDING:
            visitor.status = VisitorStatus.APPROVED
        await session.commit()
        await session.refresh(permit)
        return permit

    async def update(
        self, session: AsyncSession, permit_id: uuid.UUID, payload: PermitUpdate
    ) -> Permit:
        permit = await self.get(session, permit_id)
        data = payload.model_dump(exclude_unset=True)
        if "vehicle_id" in data and data["vehicle_id"] is not None:
            vehicle = await session.get(Vehicle, data["vehicle_id"])
            if vehicle is None or vehicle.compound_id != permit.compound_id:
                raise BadRequestError("The vehicle does not belong to this compound")
        for field, value in data.items():
            setattr(permit, field, value)
        if permit.end_at <= permit.start_at:
            raise BadRequestError("Permit end time must be after the start time")
        if permit.status not in {PermitStatus.REVOKED}:
            permit.status = self._status_for_window(permit.start_at, permit.end_at)
        await session.commit()
        await session.refresh(permit)
        return permit

    async def revoke(
        self, session: AsyncSession, permit_id: uuid.UUID, reason: str, *, actor_id: uuid.UUID
    ) -> Permit:
        permit = await self.get(session, permit_id)
        if permit.status == PermitStatus.REVOKED:
            raise ConflictError("This permit is already revoked")
        permit.status = PermitStatus.REVOKED
        permit.revoked_at = _utcnow()
        permit.revoked_reason = reason
        permit.revoked_by_id = actor_id
        await session.commit()
        await session.refresh(permit)
        return permit

    async def delete(self, session: AsyncSession, permit_id: uuid.UUID) -> None:
        permit = await self.get(session, permit_id)
        await session.delete(permit)
        await session.commit()

    async def refresh_statuses(self, session: AsyncSession) -> int:
        """Move permits between pending/active/expired based on the clock."""
        now = _utcnow()
        permits = list(
            (
                await session.execute(
                    select(Permit).where(
                        Permit.status.in_([PermitStatus.PENDING, PermitStatus.ACTIVE])
                    )
                )
            )
            .scalars()
            .unique()
            .all()
        )
        changed = 0
        for permit in permits:
            target = self._status_for_window(permit.start_at, permit.end_at)
            if target != permit.status:
                permit.status = target
                changed += 1
        if changed:
            await session.commit()
        return changed


visitor_service = VisitorService()
permit_service = PermitService()
