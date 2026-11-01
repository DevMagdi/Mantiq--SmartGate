"""Compound and unit management."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.compound import Compound, Unit
from app.models.enums import UnitStatus
from app.models.people import Resident
from app.schemas.common import Page
from app.schemas.compound import CompoundCreate, CompoundUpdate, UnitCreate, UnitUpdate
from app.services.pagination import PageParams, apply_sort, build_page, count_rows

UNIT_SORT_COLUMNS = {
    "created_at": Unit.created_at,
    "building": Unit.building,
    "unit_number": Unit.unit_number,
    "status": Unit.status,
}


class CompoundService:
    """CRUD for compounds (top-level tenants)."""

    async def get(self, session: AsyncSession, compound_id: uuid.UUID) -> Compound:
        compound = await session.get(Compound, compound_id)
        if compound is None:
            raise NotFoundError("Compound not found", code="compound_not_found")
        return compound

    async def get_by_code(self, session: AsyncSession, code: str) -> Compound | None:
        return await session.scalar(select(Compound).where(Compound.code == code.upper()))

    async def list(
        self,
        session: AsyncSession,
        params: PageParams,
        *,
        compound_id: uuid.UUID | None = None,
        is_active: bool | None = None,
        search: str | None = None,
    ) -> Page[Compound]:
        stmt = select(Compound)
        if compound_id is not None:
            stmt = stmt.where(Compound.id == compound_id)
        if is_active is not None:
            stmt = stmt.where(Compound.is_active.is_(is_active))
        if search:
            term = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(Compound.name.ilike(term), Compound.code.ilike(term), Compound.city.ilike(term))
            )
        total = await count_rows(session, stmt)
        column = {"name": Compound.name, "code": Compound.code}.get(
            params.sort_by, Compound.created_at
        )
        stmt = apply_sort(stmt, column, params.sort_dir).offset(params.offset).limit(params.page_size)
        items = list((await session.execute(stmt)).scalars().all())
        return build_page(items, total, params)

    async def create(self, session: AsyncSession, payload: CompoundCreate) -> Compound:
        if await self.get_by_code(session, payload.code):
            raise ConflictError("A compound with this code already exists", code="compound_code_taken")
        compound = Compound(**payload.model_dump())
        compound.code = compound.code.upper()
        session.add(compound)
        await session.commit()
        await session.refresh(compound)
        return compound

    async def update(
        self, session: AsyncSession, compound_id: uuid.UUID, payload: CompoundUpdate
    ) -> Compound:
        compound = await self.get(session, compound_id)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(compound, field, value)
        await session.commit()
        await session.refresh(compound)
        return compound

    async def update_settings(
        self,
        session: AsyncSession,
        compound_id: uuid.UUID,
        patch: dict[str, Any],
    ) -> Compound:
        """Deep-merge a policy patch into ``compound.settings``.

        Unknown keys written by older releases are preserved; incoming secrets
        set to the mask placeholder are ignored so a round-trip through the UI
        cannot erase them.
        """
        from app.services.compound_policy import CompoundPolicy

        compound = await self.get(session, compound_id)
        merged = _deep_merge(dict(compound.settings or {}), patch)
        _drop_masked_secrets(merged)
        # Validate by parsing: invalid values are clamped to safe defaults.
        policy = CompoundPolicy.from_settings(merged)
        merged["vision"] = policy.vision.to_dict()
        merged["access"] = policy.access.to_dict()
        merged["barrier"] = policy.barrier.to_dict(mask_secrets=False)
        compound.settings = merged
        await session.commit()
        await session.refresh(compound)
        return compound

    async def delete(self, session: AsyncSession, compound_id: uuid.UUID) -> None:
        from app.models.access import AccessLog

        compound = await self.get(session, compound_id)
        log_count = await session.scalar(
            select(func.count(AccessLog.id)).where(AccessLog.compound_id == compound_id)
        )
        if log_count:
            raise ConflictError(
                "This compound already has access history and cannot be deleted. "
                "Deactivate it instead.",
                code="compound_has_history",
            )
        await session.delete(compound)
        await session.commit()


class UnitService:
    """CRUD for units within a compound."""

    async def get(self, session: AsyncSession, unit_id: uuid.UUID) -> Unit:
        unit = await session.get(Unit, unit_id)
        if unit is None:
            raise NotFoundError("Unit not found", code="unit_not_found")
        return unit

    async def list(
        self,
        session: AsyncSession,
        params: PageParams,
        *,
        compound_id: uuid.UUID | None,
        status: UnitStatus | None = None,
        building: str | None = None,
        search: str | None = None,
    ) -> Page[Unit]:
        stmt = select(Unit)
        if compound_id is not None:
            stmt = stmt.where(Unit.compound_id == compound_id)
        if status is not None:
            stmt = stmt.where(Unit.status == status)
        if building:
            stmt = stmt.where(Unit.building == building)
        if search:
            term = f"%{search.strip()}%"
            stmt = stmt.where(or_(Unit.building.ilike(term), Unit.unit_number.ilike(term)))
        total = await count_rows(session, stmt)
        stmt = apply_sort(
            stmt, UNIT_SORT_COLUMNS.get(params.sort_by, Unit.created_at), params.sort_dir
        ).offset(params.offset).limit(params.page_size)
        items = list((await session.execute(stmt)).scalars().all())
        return build_page(items, total, params)

    async def create(self, session: AsyncSession, payload: UnitCreate) -> Unit:
        duplicate = await session.scalar(
            select(Unit).where(
                Unit.compound_id == payload.compound_id,
                Unit.building == payload.building,
                Unit.unit_number == payload.unit_number,
            )
        )
        if duplicate is not None:
            raise ConflictError(
                "A unit with this building/number already exists", code="unit_exists"
            )
        unit = Unit(**payload.model_dump())
        session.add(unit)
        await session.commit()
        await session.refresh(unit)
        return unit

    async def update(self, session: AsyncSession, unit_id: uuid.UUID, payload: UnitUpdate) -> Unit:
        unit = await self.get(session, unit_id)
        data = payload.model_dump(exclude_unset=True)
        new_building = data.get("building", unit.building)
        new_number = data.get("unit_number", unit.unit_number)
        if new_building != unit.building or new_number != unit.unit_number:
            duplicate = await session.scalar(
                select(Unit).where(
                    Unit.compound_id == unit.compound_id,
                    Unit.building == new_building,
                    Unit.unit_number == new_number,
                    Unit.id != unit.id,
                )
            )
            if duplicate is not None:
                raise ConflictError("A unit with this building/number already exists")
        for field, value in data.items():
            setattr(unit, field, value)
        await session.commit()
        await session.refresh(unit)
        return unit

    async def delete(self, session: AsyncSession, unit_id: uuid.UUID) -> None:
        unit = await self.get(session, unit_id)
        residents = await session.scalar(
            select(func.count(Resident.id)).where(Resident.unit_id == unit_id)
        )
        if residents:
            raise ConflictError(
                "This unit still has residents attached and cannot be deleted",
                code="unit_has_residents",
            )
        await session.delete(unit)
        await session.commit()

    @staticmethod
    async def sync_occupancy(session: AsyncSession, unit_id: uuid.UUID) -> None:
        """Recompute a unit's occupancy from its resident records."""
        unit = await session.get(Unit, unit_id)
        if unit is None:
            return
        active_residents = await session.scalar(
            select(func.count(Resident.id)).where(
                Resident.unit_id == unit_id, Resident.status == "active"
            )
        )
        unit.status = UnitStatus.OCCUPIED if active_residents else UnitStatus.VACANT


compound_service = CompoundService()
unit_service = UnitService()


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``patch`` into ``base`` without mutating the input."""
    merged = dict(base)
    for key, value in patch.items():
        if value is None:
            continue
        current = merged.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _drop_masked_secrets(document: dict[str, Any]) -> None:
    """Remove ``********`` placeholders so masked read-modify-write is safe."""
    barrier = document.get("barrier")
    if not isinstance(barrier, dict):
        return
    for section in ("webhook", "mqtt"):
        block = barrier.get(section)
        if not isinstance(block, dict):
            continue
        for key in ("secret", "password"):
            if block.get(key) == "********":
                block.pop(key, None)
