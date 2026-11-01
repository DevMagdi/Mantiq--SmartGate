"""Detection ingestion: vision result → decision → audit log → events."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.events import publish_event
from app.core.exceptions import BadRequestError
from app.core.logging import get_logger
from app.cv.engine import VisionEngine, get_vision_engine
from app.cv.gate_controller import AccessDecisionEngine, DecisionContext, DecisionResult, get_gate_controller
from app.cv.snapshots import SnapshotStore
from app.cv.demo_data import mock_meta_for_scenario, scenario_by_key
from app.cv.types import VisionResult
from app.cv.utils import clean_plate_text, format_plate, normalize_plate
from app.db.session import session_scope
from app.models.access import AccessLog, DetectionEvent
from app.models.base import as_utc
from app.models.compound import Camera, Compound, Gate
from app.models.enums import (
    AccessDecision,
    AccessDirection,
    AccessMethod,
    DetectionType,
    VisitorStatus,
)
from app.models.people import Permit
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.face_service import decode_image, face_service
from app.services.vehicle_service import vehicle_service
from app.cv.worker import ResultEnvelope

logger = get_logger(__name__)


@dataclass(slots=True)
class RecordedDetection:
    """Identifiers and outcome of a persisted detection."""

    access_log: AccessLog
    detection_event: DetectionEvent
    decision: DecisionResult
    vision: VisionResult

    @property
    def access_log_id(self) -> uuid.UUID:
        return self.access_log.id

    @property
    def detection_event_id(self) -> uuid.UUID:
        return self.detection_event.id


class DetectionService:
    """Turns raw vision results into auditable access decisions."""

    def __init__(
        self,
        engine: VisionEngine | None = None,
        decision_engine: AccessDecisionEngine | None = None,
    ) -> None:
        self.engine = engine or get_vision_engine()
        self.decision_engine = decision_engine or AccessDecisionEngine()
        self.controller = get_gate_controller()
        self.store = SnapshotStore()

    # ------------------------------------------------------------- ingestion
    async def handle_envelope(self, envelope: ResultEnvelope) -> RecordedDetection | None:
        """Entry point used by the CV runner (own DB session per detection)."""
        async with session_scope() as session:
            gate = await session.get(Gate, envelope.camera.gate_id)
            if gate is None:
                logger.error("Detection for unknown gate %s", envelope.camera.gate_id)
                return None
            camera = await session.get(Camera, envelope.camera.camera_id)
            return await self.process(
                session,
                gate=gate,
                camera=camera,
                result=envelope.result,
                actor=None,
            )

    async def process(
        self,
        session: AsyncSession,
        *,
        gate: Gate,
        camera: Camera | None,
        result: VisionResult,
        actor: User | None = None,
        notes: str | None = None,
    ) -> RecordedDetection:
        """Evaluate access, persist the audit trail and broadcast events."""
        compound = await session.get(Compound, gate.compound_id)
        occurred_at = as_utc(result.captured_at)
        plate_display = format_plate(result.plate.text) if result.plate else None
        face_resident_id = result.face_match.resident_id if result.face_match else None
        blacklisted_embeddings = await face_service.match_blacklisted_embeddings(
            session,
            gate.compound_id,
            result.face_embedding,
        )
        context = DecisionContext(
            gate=gate,
            plate_text=plate_display,
            plate_confidence=result.plate.confidence if result.plate else None,
            face_resident_id=face_resident_id,
            face_similarity=result.face_match.similarity if result.face_match else None,
            face_embedding_id=result.face_match.embedding_id if result.face_match else None,
            blacklisted_embedding_ids=blacklisted_embeddings,
            occurred_at=occurred_at,
        )
        decision = await self.decision_engine.decide(session, context)

        # ------------------------------------------------------ gate actuation
        gate_opened = False
        if decision.open_barrier:
            command = await self.controller.execute(
                gate,
                compound,
                "open",
                f"{decision.reason} ({decision.decision.value})",
                actor=actor.email if actor else "vision-engine",
            )
            gate_opened = command.accepted

        # --------------------------------------------------------- side effects
        self._apply_presence(decision, decision.direction, occurred_at)

        # ------------------------------------------------------------- audit
        access_log = AccessLog(
            compound_id=gate.compound_id,
            gate_id=gate.id,
            camera_id=camera.id if camera else None,
            direction=decision.direction,
            occurred_at=occurred_at,
            decision=decision.decision,
            reason_code=decision.reason_code,
            reason=decision.reason,
            access_method=decision.method,
            plate_number=plate_display,
            plate_normalized=normalize_plate(plate_display) if plate_display else None,
            plate_confidence=result.plate.confidence if result.plate else None,
            face_similarity=result.face_match.similarity if result.face_match else None,
            vehicle_id=decision.vehicle.id if decision.vehicle else None,
            resident_id=decision.resident.id if decision.resident else None,
            visitor_id=decision.visitor.id if decision.visitor else None,
            permit_id=decision.permit.id if decision.permit else None,
            snapshot_url=result.plate_snapshot_url,
            face_snapshot_url=result.face_snapshot_url,
            gate_opened=gate_opened,
            notes=notes,
        )
        session.add(access_log)
        await session.flush()

        detection = DetectionEvent(
            compound_id=gate.compound_id,
            gate_id=gate.id,
            camera_id=camera.id if camera else None,
            occurred_at=occurred_at,
            event_type=self._event_type(result),
            plate_text=plate_display,
            plate_confidence=result.plate.confidence if result.plate else None,
            plate_bbox=result.plate.bbox.as_dict() if result.plate else None,
            plate_snapshot_url=result.plate_snapshot_url,
            face_snapshot_url=result.face_snapshot_url,
            face_detected=result.face is not None,
            face_matched=result.face_match is not None,
            face_similarity=result.face_match.similarity if result.face_match else None,
            matched_resident_id=face_resident_id,
            face_embedding_id=result.face_match.embedding_id if result.face_match else None,
            matched_vehicle_id=decision.vehicle.id if decision.vehicle else None,
            decision=decision.decision,
            decision_reason=decision.reason,
            access_log_id=access_log.id,
            vision_engine=result.engine,
            processing_ms=result.processing_ms,
            raw_payload={
                **result.as_payload(),
                "decision_details": decision.details,
                "camera_name": camera.name if camera else None,
                "officer": actor.email if actor else None,
            },
        )
        session.add(detection)
        await session.commit()
        await session.refresh(access_log)
        await session.refresh(detection)

        await self._publish(access_log, detection, decision, gate, compound, camera)
        logger.info(
            "Detection gate=%s plate=%s decision=%s reason=%s",
            gate.code,
            plate_display or "-",
            decision.decision.value,
            decision.reason_code,
        )
        return RecordedDetection(
            access_log=access_log,
            detection_event=detection,
            decision=decision,
            vision=result,
        )

    # ---------------------------------------------------------- image analysis
    async def analyze_image(
        self,
        session: AsyncSession,
        *,
        gate: Gate,
        image_data: bytes,
        actor: User,
        persist: bool = True,
        demo_scenario: str | None = None,
    ) -> RecordedDetection:
        """Run an uploaded image through the pipeline and record the outcome."""
        image = decode_image(image_data)
        meta: dict[str, object] | None = None
        if demo_scenario:
            if settings.CV_MODE != "mock":
                raise BadRequestError(
                    "demo_scenario is only available when CV_MODE=mock"
                )
            try:
                scenario_by_key(demo_scenario)
            except KeyError as exc:
                raise BadRequestError(f"Unknown demo scenario: {demo_scenario}") from exc
            height, width = image.shape[:2]
            meta = mock_meta_for_scenario(demo_scenario, width, height)
        gallery = await face_service.load_gallery(session, gate.compound_id)
        result = await asyncio.to_thread(
            self.engine.analyze_image, image, gallery, meta
        )
        return await self.process(
            session,
            gate=gate,
            camera=None,
            result=result,
            actor=actor,
            notes=f"Manual image analysis by {actor.full_name}" if persist else None,
        )

    # ------------------------------------------------------------- internals
    @staticmethod
    def _event_type(result: VisionResult) -> DetectionType:
        if result.plate is not None and result.face is not None:
            return DetectionType.COMBINED
        if result.plate is not None:
            return DetectionType.PLATE
        if result.face is not None:
            return DetectionType.FACE
        return DetectionType.MANUAL

    def _apply_presence(
        self, decision: DecisionResult, direction: AccessDirection, moment: datetime
    ) -> None:
        if decision.decision != AccessDecision.ALLOW:
            return
        vehicle: Vehicle | None = decision.vehicle
        if vehicle is not None:
            vehicle.is_inside = direction == AccessDirection.ENTRY
            vehicle.last_seen_at = moment
        permit: Permit | None = decision.permit
        if permit is None:
            return
        visitor = permit.visitor
        if direction == AccessDirection.ENTRY:
            permit.entries_used = min(permit.entries_used + 1, permit.max_entries)
            if visitor is not None:
                visitor.status = VisitorStatus.CHECKED_IN
                visitor.actual_arrival = visitor.actual_arrival or moment
        elif visitor is not None and visitor.status == VisitorStatus.CHECKED_IN:
            visitor.status = VisitorStatus.CHECKED_OUT
            visitor.actual_departure = moment

    async def _publish(
        self,
        log: AccessLog,
        detection: DetectionEvent,
        decision: DecisionResult,
        gate: Gate,
        compound: Compound | None,
        camera: Camera | None,
    ) -> None:
        payload: dict[str, Any] = {
            "access_log_id": str(log.id),
            "detection_event_id": str(detection.id),
            "gate_id": str(gate.id),
            "gate_name": gate.name,
            "gate_code": gate.code,
            "compound_id": str(gate.compound_id),
            "compound_name": compound.name if compound else None,
            "camera_id": str(camera.id) if camera else None,
            "camera_name": camera.name if camera else None,
            "direction": log.direction.value,
            "decision": decision.decision.value,
            "reason_code": decision.reason_code,
            "reason": decision.reason,
            "method": decision.method.value,
            "plate_text": log.plate_number,
            "plate_confidence": round(log.plate_confidence, 4)
            if log.plate_confidence is not None
            else None,
            "face_similarity": round(log.face_similarity, 4)
            if log.face_similarity is not None
            else None,
            "face_matched": detection.face_matched,
            "face_detected": detection.face_detected,
            "requires_review": decision.requires_review,
            "resident_id": str(decision.resident.id) if decision.resident else None,
            "resident_name": decision.resident.full_name if decision.resident else None,
            "visitor_id": str(decision.visitor.id) if decision.visitor else None,
            "visitor_name": decision.visitor.full_name if decision.visitor else None,
            "vehicle_id": str(decision.vehicle.id) if decision.vehicle else None,
            "vehicle_plate": decision.vehicle.plate_number if decision.vehicle else log.plate_number,
            "permit_code": decision.permit.permit_code if decision.permit else None,
            "snapshot_url": log.snapshot_url,
            "face_snapshot_url": log.face_snapshot_url,
            "gate_opened": log.gate_opened,
            "occurred_at": log.occurred_at.isoformat(),
            "processing_ms": detection.processing_ms,
        }
        await publish_event("detection.created", payload)
        await publish_event(
            "access.decision",
            {
                "access_log_id": str(log.id),
                "gate_id": str(gate.id),
                "decision": decision.decision.value,
                "reason_code": decision.reason_code,
                "direction": log.direction.value,
                "requires_review": decision.requires_review,
                "gate_opened": log.gate_opened,
                "occurred_at": log.occurred_at.isoformat(),
            },
        )


detection_service = DetectionService()


__all__ = ["DetectionService", "RecordedDetection", "detection_service"]
