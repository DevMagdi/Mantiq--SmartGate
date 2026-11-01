"""Resident lifecycle management, including optional portal accounts."""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.security import hash_password
from app.models.compound import Unit
from app.models.enums import ResidentStatus, UnitStatus, UserRole
from app.models.people import Resident
from app.models.security import FaceEmbedding
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.common import Page
from app.schemas.people import ResidentCreate, ResidentUpdate
from app.services.pagination import PageParams, apply_sort, build_page, count_rows


class ResidentService:
    """CRUD for residents and their optional login accounts."""

    async def get(self, session: AsyncSession, resident_id: uuid.UUID) -> Resident:
        resident = await session.get(Resident, resident_id)
        if resident is None:
            raise NotFoundError("Resident not found", code="resident_not_found")
        return resident

    async def get_by_user(self, session: AsyncSession, user_id: uuid.UUID) -> Resident | None:
        return await session.scalar(select(Resident).where(Resident.user_id == user_id))

    async def list(
        self,
        session: AsyncSession,
        params: PageParams,
        *,
        compound_id: uuid.UUID | None,
        unit_id: uuid.UUID | None = None,
        status: ResidentStatus | None = None,
        search: str | None = None,
    ) -> Page[Resident]:
        stmt = select(Resident)
        if compound_id is not None:
            stmt = stmt.where(Resident.compound_id == compound_id)
        if unit_id is not None:
            stmt = stmt.where(Resident.unit_id == unit_id)
        if status is not None:
            stmt = stmt.where(Resident.status == status)
        if search:
            term = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    Resident.full_name.ilike(term),
                    Resident.phone.ilike(term),
                    Resident.email.ilike(term),
                    Resident.national_id.ilike(term),
                )
            )
        total = await count_rows(session, stmt)
        columns = {
            "created_at": Resident.created_at,
            "full_name": Resident.full_name,
            "status": Resident.status,
        }
        stmt = apply_sort(stmt, columns.get(params.sort_by, Resident.created_at), params.sort_dir)
        stmt = stmt.offset(params.offset).limit(params.page_size)
        residents = list((await session.execute(stmt)).scalars().unique().all())
        await self._attach_counts(session, residents)
        return build_page(residents, total, params)

    async def _attach_counts(self, session: AsyncSession, residents: list[Resident]) -> None:
        if not residents:
            return
        ids = [resident.id for resident in residents]
        vehicle_rows = (
            await session.execute(
                select(Vehicle.resident_id, func.count(Vehicle.id))
                .where(Vehicle.resident_id.in_(ids))
                .group_by(Vehicle.resident_id)
            )
        ).all()
        face_rows = (
            await session.execute(
                select(FaceEmbedding.resident_id, func.count(FaceEmbedding.id))
                .where(
                    FaceEmbedding.resident_id.in_(ids), FaceEmbedding.is_active.is_(True)
                )
                .group_by(FaceEmbedding.resident_id)
            )
        ).all()
        vehicle_counts = {row[0]: int(row[1]) for row in vehicle_rows}
        face_counts = {row[0]: int(row[1]) for row in face_rows}
        for resident in residents:
            resident.vehicle_count = vehicle_counts.get(resident.id, 0)  # type: ignore[attr-defined]
            resident.face_count = face_counts.get(resident.id, 0)  # type: ignore[attr-defined]

    async def create(self, session: AsyncSession, payload: ResidentCreate, *, actor: User) -> Resident:
        unit = await session.get(Unit, payload.unit_id)
        if unit is None or unit.compound_id != payload.compound_id:
            raise BadRequestError("The selected unit does not belong to this compound")
        if payload.national_id:
            duplicate_nid = await session.scalar(
                select(Resident).where(
                    Resident.compound_id == payload.compound_id,
                    Resident.national_id == payload.national_id,
                )
            )
            if duplicate_nid is not None:
                raise ConflictError(
                    "A resident with this national id already exists in the compound",
                    code="national_id_taken",
                )

        user: User | None = None
        if payload.user_id is not None:
            user = await session.get(User, payload.user_id)
            if user is None:
                raise BadRequestError("The linked user account does not exist")
            existing_link = await session.scalar(
                select(Resident).where(Resident.user_id == payload.user_id)
            )
            if existing_link is not None:
                raise ConflictError("This user account is already linked to another resident")
        elif payload.create_account:
            assert payload.email and payload.account_password
            email = payload.email.lower()
            if await session.scalar(select(User).where(User.email == email)):
                raise ConflictError("A user with this email already exists", code="email_taken")
            user = User(
                email=email,
                hashed_password=hash_password(payload.account_password),
                full_name=payload.full_name,
                phone=payload.phone,
                role=UserRole.RESIDENT,
                compound_id=payload.compound_id,
            )
            session.add(user)
            await session.flush()

        data = payload.model_dump(
            exclude={"create_account", "account_password", "user_id", "email"}
        )
        resident = Resident(
            **data,
            email=str(payload.email) if payload.email else None,
            user_id=user.id if user else None,
        )
        if resident.is_primary:
            await session.execute(
                update(Resident)
                .where(Resident.unit_id == resident.unit_id)
                .values(is_primary=False)
            )
        session.add(resident)
        await session.flush()
        unit.status = (
            UnitStatus.OCCUPIED if resident.status == ResidentStatus.ACTIVE else unit.status
        )
        await session.commit()
        await session.refresh(resident)
        return resident

    async def update(
        self, session: AsyncSession, resident_id: uuid.UUID, payload: ResidentUpdate
    ) -> Resident:
        resident = await self.get(session, resident_id)
        data = payload.model_dump(exclude_unset=True)
        if "unit_id" in data and data["unit_id"] != resident.unit_id:
            unit = await session.get(Unit, data["unit_id"])
            if unit is None or unit.compound_id != resident.compound_id:
                raise BadRequestError("The selected unit does not belong to this compound")
        if data.get("is_primary"):
            await session.execute(
                update(Resident)
                .where(Resident.unit_id == resident.unit_id, Resident.id != resident.id)
                .values(is_primary=False)
            )
        old_status = resident.status
        for field, value in data.items():
            setattr(resident, field, value)
        await session.flush()
        if "is_primary" in data and data["is_primary"]:
            resident.is_primary = True
        unit = await session.get(Unit, resident.unit_id)
        if unit is not None:
            if resident.status == ResidentStatus.ACTIVE:
                unit.status = UnitStatus.OCCUPIED
            elif old_status == ResidentStatus.ACTIVE and resident.status != ResidentStatus.ACTIVE:
                remaining = await session.scalar(
                    select(func.count(Resident.id)).where(
                        Resident.unit_id == unit.id,
                        Resident.status == ResidentStatus.ACTIVE,
                        Resident.id != resident.id,
                    )
                )
                if not remaining:
                    unit.status = UnitStatus.VACANT
        await session.commit()
        await session.refresh(resident)
        return resident

    async def delete(self, session: AsyncSession, resident_id: uuid.UUID) -> None:
        resident = await self.get(session, resident_id)
        registered_vehicles = await session.scalar(
            select(func.count(Vehicle.id)).where(Vehicle.resident_id == resident_id)
        )
        if registered_vehicles:
            raise ConflictError(
                "Remove or reassign the resident's vehicles before deleting the profile",
                code="resident_has_vehicles",
            )
        unit_id = resident.unit_id
        await session.delete(resident)
        await session.flush()
        remaining = await session.scalar(
            select(func.count(Resident.id)).where(
                Resident.unit_id == unit_id, Resident.status == ResidentStatus.ACTIVE
            )
        )
        if not remaining:
            unit = await session.get(Unit, unit_id)
            if unit is not None:
                unit.status = UnitStatus.VACANT
        await session.commit()


resident_service = ResidentService()
