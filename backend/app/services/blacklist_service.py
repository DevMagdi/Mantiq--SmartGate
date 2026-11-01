"""Blacklist management for plates, faces and people."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models.enums import BlacklistEntryType
from app.models.people import Resident, Visitor
from app.models.security import BlacklistEntry, FaceEmbedding
from app.schemas.common import Page
from app.schemas.security import BlacklistCreate, BlacklistUpdate
from app.services.pagination import PageParams, apply_sort, build_page, count_rows
from app.cv.utils import format_plate, normalize_plate


class BlacklistService:
    """CRUD for blacklist entries with de-duplication."""

    async def get(self, session: AsyncSession, entry_id: uuid.UUID) -> BlacklistEntry:
        entry = await session.get(BlacklistEntry, entry_id)
        if entry is None:
            raise NotFoundError("Blacklist entry not found", code="blacklist_not_found")
        return entry

    async def list(
        self,
        session: AsyncSession,
        params: PageParams,
        *,
        compound_id: uuid.UUID | None,
        entry_type: BlacklistEntryType | None = None,
        is_active: bool | None = None,
        search: str | None = None,
    ) -> Page[BlacklistEntry]:
        stmt = select(BlacklistEntry)
        if compound_id is not None:
            stmt = stmt.where(BlacklistEntry.compound_id == compound_id)
        if entry_type is not None:
            stmt = stmt.where(BlacklistEntry.entry_type == entry_type)
        if is_active is not None:
            stmt = stmt.where(BlacklistEntry.is_active.is_(is_active))
        if search:
            term = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    BlacklistEntry.plate_number.ilike(term),
                    BlacklistEntry.person_name.ilike(term),
                    BlacklistEntry.national_id.ilike(term),
                    BlacklistEntry.description.ilike(term),
                )
            )
        total = await count_rows(session, stmt)
        column = {"created_at": BlacklistEntry.created_at}.get(
            params.sort_by, BlacklistEntry.created_at
        )
        stmt = apply_sort(stmt, column, params.sort_dir).offset(params.offset).limit(params.page_size)
        items = list((await session.execute(stmt)).scalars().unique().all())
        return build_page(items, total, params)

    async def create(
        self, session: AsyncSession, payload: BlacklistCreate, *, actor_id: uuid.UUID
    ) -> BlacklistEntry:
        normalized = normalize_plate(payload.plate_number) if payload.plate_number else None
        if payload.resident_id is not None:
            resident = await session.get(Resident, payload.resident_id)
            if resident is None or resident.compound_id != payload.compound_id:
                raise BadRequestError("The resident does not belong to this compound")
        if payload.visitor_id is not None:
            visitor = await session.get(Visitor, payload.visitor_id)
            if visitor is None or visitor.compound_id != payload.compound_id:
                raise BadRequestError("The visitor does not belong to this compound")

        embedding_id: uuid.UUID | None = None
        if payload.entry_type == BlacklistEntryType.FACE:
            embedding_id = await self._resolve_face_embedding(
                session, payload.compound_id, payload.resident_id
            )
        duplicate_conditions = []
        if normalized:
            duplicate_conditions.append(
                BlacklistEntry.plate_normalized == normalized
            )
        if payload.resident_id:
            duplicate_conditions.append(BlacklistEntry.resident_id == payload.resident_id)
        if duplicate_conditions:
            duplicate = await session.scalar(
                select(BlacklistEntry).where(
                    BlacklistEntry.compound_id == payload.compound_id,
                    BlacklistEntry.is_active.is_(True),
                    or_(*duplicate_conditions),
                )
            )
            if duplicate is not None:
                raise ConflictError(
                    "An active blacklist entry already exists for this plate/person",
                    code="blacklist_duplicate",
                )

        entry = BlacklistEntry(
            **payload.model_dump(exclude={"plate_number"}),
            plate_number=format_plate(payload.plate_number) if payload.plate_number else None,
            plate_normalized=normalized,
            face_embedding_id=embedding_id,
            created_by_id=actor_id,
        )
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
        return entry

    async def _resolve_face_embedding(
        self, session: AsyncSession, compound_id: uuid.UUID, resident_id: uuid.UUID | None
    ) -> uuid.UUID:
        if resident_id is None:
            raise BadRequestError(
                "A resident with an enrolled face is required for a face blacklist entry"
            )
        embedding = await session.scalar(
            select(FaceEmbedding)
            .where(
                FaceEmbedding.resident_id == resident_id,
                FaceEmbedding.is_active.is_(True),
            )
            .order_by(FaceEmbedding.created_at.desc())
        )
        if embedding is None:
            raise BadRequestError(
                "This resident has no enrolled face; enroll a face before blacklisting",
                code="no_face_enrolled",
            )
        return embedding.id

    async def update(
        self, session: AsyncSession, entry_id: uuid.UUID, payload: BlacklistUpdate
    ) -> BlacklistEntry:
        entry = await self.get(session, entry_id)
        data = payload.model_dump(exclude_unset=True)
        if "plate_number" in data:
            plate = data.pop("plate_number")
            entry.plate_number = plate.strip() if plate else None
            entry.plate_normalized = normalize_plate(plate) if plate else None
        for field, value in data.items():
            setattr(entry, field, value)
        await session.commit()
        await session.refresh(entry)
        return entry

    async def delete(self, session: AsyncSession, entry_id: uuid.UUID) -> None:
        entry = await self.get(session, entry_id)
        await session.delete(entry)
        await session.commit()


blacklist_service = BlacklistService()
