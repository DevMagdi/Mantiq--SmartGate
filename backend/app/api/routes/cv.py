"""Computer vision administration endpoints."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, File, Form, UploadFile, status

from app.api.deps import CompoundScope, ManagerUser, SessionDep
from app.core.events import publish_event
from app.core.exceptions import BadRequestError
from app.cv.manager import get_camera_manager
from app.schemas.access import VisionAnalyzeResponse, VisionPipelineStatus
from app.schemas.common import Message
from app.schemas.security import FaceGalleryInfo
from app.services.access_service import access_service
from app.services.cv_service import cv_service
from app.services.detection_service import detection_service
from app.services.face_service import face_service
from app.services.gate_service import gate_service
from app.services.permissions import enforce_compound

router = APIRouter(prefix="/cv", tags=["Computer Vision"])


@router.get("/status", response_model=VisionPipelineStatus, summary="Vision engine status")
async def pipeline_status(
    session: SessionDep, manager: ManagerUser, compound_id: CompoundScope
) -> VisionPipelineStatus:
    return await cv_service.pipeline_status(session, compound_id)


@router.post("/warmup", response_model=VisionPipelineStatus, summary="Load CV models")
async def warmup(
    session: SessionDep, manager: ManagerUser, compound_id: CompoundScope
) -> VisionPipelineStatus:
    await cv_service.warmup()
    return await cv_service.pipeline_status(session, compound_id)


@router.get("/gallery", response_model=FaceGalleryInfo, summary="Face gallery statistics")
async def gallery(
    session: SessionDep, manager: ManagerUser, compound_id: CompoundScope
) -> FaceGalleryInfo:
    return await face_service.gallery_info(session, compound_id)


@router.post("/refresh-gallery", response_model=Message, summary="Reload the face gallery")
async def refresh_gallery(manager: ManagerUser) -> Message:
    camera_manager = get_camera_manager()
    if camera_manager is not None:
        await camera_manager.refresh_galleries()
    await publish_event("gallery.updated", {"requested_by": manager.email})
    return Message(message="Face gallery refresh requested")


@router.get("/workers", summary="In-process camera worker status")
async def worker_status(manager: ManagerUser) -> dict[str, object]:
    camera_manager = get_camera_manager()
    if camera_manager is None:
        return {
            "in_process": False,
            "detail": "Vision workers run in a separate service (see docker-compose cv-worker).",
        }
    return {"in_process": True, **camera_manager.status()}


@router.post(
    "/analyze",
    response_model=VisionAnalyzeResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze an uploaded image",
    description=(
        "Runs the full plate + face pipeline on an uploaded frame, evaluates the access rules "
        "and records the result as an access log so an officer can override it if needed."
    ),
)
async def analyze_image(
    session: SessionDep,
    manager: ManagerUser,
    gate_id: uuid.UUID = Form(..., description="Gate the image belongs to"),
    file: UploadFile = File(..., description="Frame captured at the gate (JPEG/PNG)"),
    demo_scenario: str | None = Form(
        default=None,
        description="Mock mode only: replay a scripted detection scenario against the upload",
    ),
) -> VisionAnalyzeResponse:
    gate = await gate_service.get(session, gate_id)
    enforce_compound(manager, gate.compound_id)
    if not file.content_type or not file.content_type.startswith("image/"):
        raise BadRequestError("Only image uploads are supported")
    data = await file.read()
    recorded = await detection_service.analyze_image(
        session,
        gate=gate,
        image_data=data,
        actor=manager,
        demo_scenario=demo_scenario,
    )
    decision = recorded.decision
    return VisionAnalyzeResponse(
        plate_text=recorded.access_log.plate_number,
        plate_confidence=recorded.access_log.plate_confidence,
        plate_snapshot_url=recorded.access_log.snapshot_url,
        face_detected=recorded.detection_event.face_detected,
        face_matched=recorded.detection_event.face_matched,
        face_similarity=recorded.access_log.face_similarity,
        matched_resident_id=decision.resident.id if decision.resident else None,
        decision=decision.decision,
        reason_code=decision.reason_code,
        reason=decision.reason,
        access_method=decision.method,
        detection_event_id=recorded.detection_event_id,
        access_log_id=recorded.access_log_id,
        processing_ms=recorded.vision.processing_ms,
    )


@router.get("/camera-health", summary="Camera status counts")
async def camera_health(
    session: SessionDep, manager: ManagerUser, compound_id: CompoundScope
) -> dict[str, int]:
    return await cv_service.camera_health(session, compound_id)


@router.post("/analysis/{log_id}/confirm", response_model=Message, summary="Confirm a review")
async def confirm_analysis(
    log_id: uuid.UUID, session: SessionDep, manager: ManagerUser
) -> Message:
    """Acknowledge a manual-review detection (audit note only)."""
    from app.models.enums import AccessDecision

    log = await access_service.get_log(session, log_id)
    enforce_compound(manager, log.compound_id)
    if log.decision != AccessDecision.REVIEW:
        raise BadRequestError("Only detections awaiting review can be confirmed")
    log.notes = (log.notes or "") + f"\nReviewed by {manager.full_name}"
    await session.commit()
    await asyncio.sleep(0)
    return Message(message="Review acknowledged")
