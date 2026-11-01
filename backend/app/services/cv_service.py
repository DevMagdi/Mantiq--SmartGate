"""Computer vision related service helpers exposed through the API."""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.events import publish_event
from app.core.logging import get_logger
from app.core.metrics import set_engine_state
from app.cv.engine import get_vision_engine
from app.cv.gate_controller import GateController, get_gate_controller
from app.models.compound import Camera, Compound, Gate
from app.models.enums import CameraStatus
from app.models.security import FaceEmbedding
from app.schemas.access import (
    ActuatorCommandRead,
    ActuatorStatus,
    ActuatorStatusResponse,
    GateCommandResult,
    VisionPipelineStatus,
)
from app.services.compound_policy import CompoundPolicy
from app.schemas.security import FaceGalleryInfo

logger = get_logger(__name__)


class CvService:
    """Bridges HTTP requests to the vision engine and gate controller."""

    def __init__(self) -> None:
        self.engine = get_vision_engine()
        self.controller: GateController = get_gate_controller()

    async def pipeline_status(
        self, session: AsyncSession, compound_id: uuid.UUID | None
    ) -> VisionPipelineStatus:
        engine_status = self.engine.status()
        stmt = select(func.count(FaceEmbedding.id)).where(FaceEmbedding.is_active.is_(True))
        if compound_id is not None:
            stmt = stmt.where(FaceEmbedding.compound_id == compound_id)
        gallery_size = int(await session.scalar(stmt) or 0)
        set_engine_state(
            ready=bool(engine_status["engine_ready"]),
            mode=str(engine_status["mode"]),
            gallery_entries=gallery_size,
        )
        return VisionPipelineStatus(
            mode=str(engine_status["mode"]),
            plate_detector=str(engine_status["plate_detector"]),
            ocr_engine=str(engine_status["ocr_engine"]),
            face_engine=str(engine_status["face_engine"]),
            engine_ready=bool(engine_status["engine_ready"]),
            models_loaded=list(engine_status["models_loaded"]),  # type: ignore[arg-type]
            warnings=list(engine_status["warnings"]),  # type: ignore[arg-type]
            face_gallery_size=gallery_size,
            similarity_threshold=float(settings.CV_FACE_SIMILARITY_THRESHOLD),
        )

    async def warmup(self) -> bool:
        """Load models in a worker thread."""
        return await self.engine.warmup_async()

    async def gallery_info(
        self, session: AsyncSession, compound_id: uuid.UUID | None
    ) -> FaceGalleryInfo:
        from app.services.face_service import face_service

        return await face_service.gallery_info(session, compound_id)

    async def command_gate(
        self,
        session: AsyncSession,
        gate: Gate,
        action: str,
        reason: str,
        *,
        actor: str,
    ) -> GateCommandResult:
        compound = await session.get(Compound, gate.compound_id)
        command = await self.controller.execute(gate, compound, action, reason, actor=actor)
        return GateCommandResult(
            gate_id=gate.id,
            action=action,
            accepted=command.accepted,
            detail=command.detail,
            driver=command.driver,
            latency_ms=command.latency_ms,
            command_id=command.command_id,
        )

    async def actuator_status(
        self, session: AsyncSession, compound_id: uuid.UUID | None
    ) -> ActuatorStatusResponse:
        """Return barrier driver health and recent commands per compound."""
        stmt = select(Compound).order_by(Compound.name)
        if compound_id is not None:
            stmt = stmt.where(Compound.id == compound_id)
        compounds = list((await session.execute(stmt)).scalars().all())
        registry = self.controller.registry
        entries: list[ActuatorStatus] = []
        for compound in compounds:
            policy = CompoundPolicy.from_settings(compound.settings)
            try:
                await registry.for_policy(compound.id, policy.barrier)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Could not prepare actuator for %s: %s", compound.id, exc)
            snapshot = registry.status(compound.id)
            entries.append(
                ActuatorStatus(
                    compound_id=compound.id,
                    compound_name=compound.name,
                    configured=bool(snapshot.get("configured")),
                    driver=str(snapshot.get("driver") or "simulator"),
                    name=snapshot.get("name"),
                    config=dict(snapshot.get("config") or {}),
                    health=dict(snapshot.get("health") or {}),
                    warnings=list(snapshot.get("warnings") or []),
                    journal=self.controller.journal.summary(),
                    recent_commands=[
                        ActuatorCommandRead(**item.as_dict())
                        for item in self.controller.journal.recent(
                            10, compound_id=str(compound.id)
                        )
                    ],
                )
            )
        return ActuatorStatusResponse(
            compounds=entries, journal=self.controller.journal.summary()
        )

    async def camera_health(self, session: AsyncSession, compound_id: uuid.UUID | None) -> dict[str, int]:
        stmt = select(Camera.status, func.count(Camera.id))
        if compound_id is not None:
            stmt = stmt.join(Gate, Camera.gate_id == Gate.id).where(Gate.compound_id == compound_id)
        stmt = stmt.group_by(Camera.status)
        rows = (await session.execute(stmt)).all()
        counts = {status.value: 0 for status in CameraStatus}
        for status, count in rows:
            counts[status.value] = int(count)
        counts["total"] = sum(counts.values())
        return counts

    async def refresh_gallery(self) -> None:
        """Notify other processes that the face gallery must be reloaded."""
        await publish_event("gallery.updated", {"requested_at": asyncio.get_event_loop().time()})


cv_service = CvService()
