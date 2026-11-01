"""Gate and camera management."""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.access import AccessLog
from app.models.compound import Camera, Gate
from app.models.enums import CameraStatus, GateStatus
from app.schemas.common import Page
from app.schemas.compound import CameraCreate, CameraUpdate, GateCreate, GateUpdate
from app.services.pagination import PageParams, apply_sort, build_page, count_rows


class GateService:
    """CRUD for gates."""

    async def get(self, session: AsyncSession, gate_id: uuid.UUID) -> Gate:
        gate = await session.get(Gate, gate_id)
        if gate is None:
            raise NotFoundError("Gate not found", code="gate_not_found")
        return gate

    async def list(
        self,
        session: AsyncSession,
        params: PageParams,
        *,
        compound_id: uuid.UUID | None,
        status: GateStatus | None = None,
        search: str | None = None,
    ) -> Page[Gate]:
        stmt = select(Gate)
        if compound_id is not None:
            stmt = stmt.where(Gate.compound_id == compound_id)
        if status is not None:
            stmt = stmt.where(Gate.status == status)
        if search:
            term = f"%{search.strip().lower()}%"
            stmt = stmt.where(or_(Gate.name.ilike(term), Gate.code.ilike(term)))
        total = await count_rows(session, stmt)
        column = {"name": Gate.name, "code": Gate.code}.get(params.sort_by, Gate.created_at)
        stmt = apply_sort(stmt, column, params.sort_dir).offset(params.offset).limit(params.page_size)
        items = list((await session.execute(stmt)).scalars().unique().all())
        return build_page(items, total, params)

    async def create(self, session: AsyncSession, payload: GateCreate) -> Gate:
        duplicate = await session.scalar(
            select(Gate).where(Gate.compound_id == payload.compound_id, Gate.code == payload.code)
        )
        if duplicate is not None:
            raise ConflictError("A gate with this code already exists in the compound")
        gate = Gate(**payload.model_dump())
        gate.code = gate.code.upper()
        session.add(gate)
        await session.commit()
        await session.refresh(gate)
        return gate

    async def update(self, session: AsyncSession, gate_id: uuid.UUID, payload: GateUpdate) -> Gate:
        gate = await self.get(session, gate_id)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(gate, field, value)
        await session.commit()
        await session.refresh(gate)
        return gate

    async def delete(self, session: AsyncSession, gate_id: uuid.UUID) -> None:
        gate = await self.get(session, gate_id)
        history = await session.scalar(select(func.count(AccessLog.id)).where(AccessLog.gate_id == gate_id))
        if history:
            raise ConflictError(
                "This gate has access history and cannot be deleted. Mark it inactive instead.",
                code="gate_has_history",
            )
        await session.delete(gate)
        await session.commit()


class CameraService:
    """CRUD for cameras plus live status."""

    async def get(self, session: AsyncSession, camera_id: uuid.UUID) -> Camera:
        camera = await session.get(Camera, camera_id)
        if camera is None:
            raise NotFoundError("Camera not found", code="camera_not_found")
        return camera

    async def list(
        self,
        session: AsyncSession,
        params: PageParams,
        *,
        gate_id: uuid.UUID | None = None,
        compound_id: uuid.UUID | None = None,
        status: CameraStatus | None = None,
        is_active: bool | None = None,
        search: str | None = None,
    ) -> Page[Camera]:
        stmt = select(Camera)
        if gate_id is not None:
            stmt = stmt.where(Camera.gate_id == gate_id)
        if compound_id is not None:
            stmt = stmt.join(Gate, Camera.gate_id == Gate.id).where(Gate.compound_id == compound_id)
        if status is not None:
            stmt = stmt.where(Camera.status == status)
        if is_active is not None:
            stmt = stmt.where(Camera.is_active.is_(is_active))
        if search:
            term = f"%{search.strip().lower()}%"
            stmt = stmt.where(or_(Camera.name.ilike(term), Camera.source_url.ilike(term)))
        total = await count_rows(session, stmt)
        column = {"name": Camera.name, "status": Camera.status}.get(params.sort_by, Camera.created_at)
        stmt = apply_sort(stmt, column, params.sort_dir).offset(params.offset).limit(params.page_size)
        items = list((await session.execute(stmt)).scalars().unique().all())
        return build_page(items, total, params)

    async def create(self, session: AsyncSession, payload: CameraCreate) -> Camera:
        duplicate = await session.scalar(
            select(Camera).where(Camera.gate_id == payload.gate_id, Camera.name == payload.name)
        )
        if duplicate is not None:
            raise ConflictError("A camera with this name already exists on the gate")
        camera = Camera(**payload.model_dump())
        camera.status = CameraStatus.DISABLED if not camera.is_active else CameraStatus.OFFLINE
        session.add(camera)
        await session.commit()
        await session.refresh(camera)
        return camera

    async def update(
        self, session: AsyncSession, camera_id: uuid.UUID, payload: CameraUpdate
    ) -> Camera:
        camera = await self.get(session, camera_id)
        data = payload.model_dump(exclude_unset=True)
        if "name" in data and data["name"] != camera.name:
            duplicate = await session.scalar(
                select(Camera).where(
                    Camera.gate_id == camera.gate_id,
                    Camera.name == data["name"],
                    Camera.id != camera.id,
                )
            )
            if duplicate is not None:
                raise ConflictError("A camera with this name already exists on the gate")
        for field, value in data.items():
            setattr(camera, field, value)
        if not camera.is_active:
            camera.status = CameraStatus.DISABLED
        await session.commit()
        await session.refresh(camera)
        return camera

    async def delete(self, session: AsyncSession, camera_id: uuid.UUID) -> None:
        camera = await self.get(session, camera_id)
        await session.delete(camera)
        await session.commit()

    async def set_active(self, session: AsyncSession, camera_id: uuid.UUID, active: bool) -> Camera:
        camera = await self.get(session, camera_id)
        camera.is_active = active
        camera.status = CameraStatus.OFFLINE if active else CameraStatus.DISABLED
        await session.commit()
        await session.refresh(camera)
        return camera


gate_service = GateService()
camera_service = CameraService()
