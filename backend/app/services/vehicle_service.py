"""Vehicle registry service."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models.enums import VehicleStatus, VehicleType
from app.models.people import Resident
from app.models.vehicle import Vehicle
from app.schemas.common import Page
from app.cv.utils import format_plate, normalize_plate
from app.services.pagination import PageParams, apply_sort, build_page, count_rows


class VehicleService:
    """CRUD for registered vehicles."""

    async def get(self, session: AsyncSession, vehicle_id: uuid.UUID) -> Vehicle:
        vehicle = await session.get(Vehicle, vehicle_id)
        if vehicle is None:
            raise NotFoundError("Vehicle not found", code="vehicle_not_found")
        return vehicle

    async def get_by_plate(self, session: AsyncSession, compound_id: uuid.UUID, plate: str) -> Vehicle | None:
        return await session.scalar(
            select(Vehicle).where(
                Vehicle.compound_id == compound_id,
                Vehicle.plate_normalized == normalize_plate(plate),
            )
        )

    async def list(
        self,
        session: AsyncSession,
        params: PageParams,
        *,
        compound_id: uuid.UUID | None,
        resident_id: uuid.UUID | None = None,
        status: VehicleStatus | None = None,
        is_inside: bool | None = None,
        search: str | None = None,
    ) -> Page[Vehicle]:
        stmt = select(Vehicle)
        if compound_id is not None:
            stmt = stmt.where(Vehicle.compound_id == compound_id)
        if resident_id is not None:
            stmt = stmt.where(Vehicle.resident_id == resident_id)
        if status is not None:
            stmt = stmt.where(Vehicle.status == status)
        if is_inside is not None:
            stmt = stmt.where(Vehicle.is_inside.is_(is_inside))
        if search:
            term = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    Vehicle.plate_number.ilike(term),
                    Vehicle.plate_normalized.ilike(term),
                    Vehicle.make.ilike(term),
                    Vehicle.model.ilike(term),
                    Vehicle.color.ilike(term),
                )
            )
        total = await count_rows(session, stmt)
        columns = {
            "plate_number": Vehicle.plate_number,
            "created_at": Vehicle.created_at,
            "last_seen_at": Vehicle.last_seen_at,
        }
        stmt = apply_sort(stmt, columns.get(params.sort_by, Vehicle.created_at), params.sort_dir)
        stmt = stmt.offset(params.offset).limit(params.page_size)
        items = list((await session.execute(stmt)).scalars().unique().all())
        return build_page(items, total, params)

    async def create(self, session: AsyncSession, payload: VehicleCreate) -> Vehicle:
        resident: Resident | None = None
        if payload.resident_id is not None:
            resident = await session.get(Resident, payload.resident_id)
            if resident is None or resident.compound_id != payload.compound_id:
                raise BadRequestError("The selected resident does not belong to this compound")
        normalized = normalize_plate(payload.plate_number)
        if await self.get_by_plate(session, payload.compound_id, payload.plate_number):
            raise ConflictError("A vehicle with this plate already exists", code="plate_taken")
        vehicle = Vehicle(
            **payload.model_dump(exclude={"resident_id", "plate_number"}),
            plate_number=format_plate(payload.plate_number),
            resident_id=resident.id if resident else None,
            plate_normalized=normalized,
        )
        session.add(vehicle)
        await session.commit()
        await session.refresh(vehicle)
        return vehicle

    async def update(
        self, session: AsyncSession, vehicle_id: uuid.UUID, payload: VehicleUpdate
    ) -> Vehicle:
        vehicle = await self.get(session, vehicle_id)
        data = payload.model_dump(exclude_unset=True)
        if "resident_id" in data and data["resident_id"] is not None:
            resident = await session.get(Resident, data["resident_id"])
            if resident is None or resident.compound_id != vehicle.compound_id:
                raise BadRequestError("The selected resident does not belong to this compound")
        if "plate_number" in data and data["plate_number"]:
            normalized = normalize_plate(str(data["plate_number"]))
            duplicate = await session.scalar(
                select(Vehicle).where(
                    Vehicle.compound_id == vehicle.compound_id,
                    Vehicle.plate_normalized == normalized,
                    Vehicle.id != vehicle.id,
                )
            )
            if duplicate is not None:
                raise ConflictError("A vehicle with this plate already exists", code="plate_taken")
            vehicle.plate_normalized = normalized
            vehicle.plate_number = format_plate(str(data["plate_number"]))
        for field, value in data.items():
            if field == "plate_normalized":
                continue
            setattr(vehicle, field, value)
        await session.commit()
        await session.refresh(vehicle)
        return vehicle

    async def delete(self, session: AsyncSession, vehicle_id: uuid.UUID) -> None:
        vehicle = await self.get(session, vehicle_id)
        await session.delete(vehicle)
        await session.commit()

    async def ensure_visitor_vehicle(
        self, session: AsyncSession, compound_id: uuid.UUID, plate: str
    ) -> Vehicle:
        """Return an existing vehicle or register an unowned visitor vehicle."""
        normalized = normalize_plate(plate)
        if len(normalized) < 3:
            raise BadRequestError("Plate number is too short")
        existing = await self.get_by_plate(session, compound_id, plate)
        if existing is not None:
            return existing
        vehicle = Vehicle(
            compound_id=compound_id,
            plate_number=format_plate(plate),
            plate_normalized=normalized,
            vehicle_type=VehicleType.CAR,
        )
        session.add(vehicle)
        await session.flush()
        return vehicle


vehicle_service = VehicleService()
