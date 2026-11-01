"""Computer vision administration endpoints."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, File, Form, Response, UploadFile, status

from app.api.deps import CompoundScope, ManagerUser, SessionDep
from app.core.events import publish_event
from app.core.exceptions import BadRequestError
from app.cv.manager import get_camera_manager
from app.schemas.access import (
    ActuatorStatusResponse,
    ActuatorTestRequest,
    GateCommandResult,
    VisionAnalyzeResponse,
    VisionPipelineStatus,
)
from app.schemas.camera import CameraHealthResponse, CameraProbeResponse, RealModeStatus
from app.schemas.common import Message
from app.schemas.security import FaceGalleryInfo
from app.services.access_service import access_service
from app.services.cv_service import cv_service
from app.services.camera_service import camera_service
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


@router.get(
    "/actuators",
    response_model=ActuatorStatusResponse,
    summary="Barrier actuator drivers and recent commands",
)
async def actuator_status(
    session: SessionDep, manager: ManagerUser, compound_id: CompoundScope
) -> ActuatorStatusResponse:
    """Configuration, health and the last commands of every barrier driver."""
    return await cv_service.actuator_status(session, compound_id)


@router.post(
    "/actuators/test",
    response_model=GateCommandResult,
    summary="Send a test command to a barrier driver",
)
async def test_actuator(
    payload: ActuatorTestRequest, session: SessionDep, manager: ManagerUser
) -> GateCommandResult:
    """Send a single command through the configured driver (audited)."""
    gate = await gate_service.get(session, payload.gate_id)
    enforce_compound(manager, gate.compound_id)
    return await cv_service.command_gate(
        session,
        gate,
        payload.action,
        "Actuator test from dashboard",
        actor=manager.email,
    )


@router.get(
    "/camera-health",
    response_model=CameraHealthResponse,
    summary="Camera health for the fleet",
    description=(
        "Per-camera status, last frame age and the last stream error, merged with the "
        "state of the live capture workers. A camera that stopped delivering frames is "
        "reported as `stale` even when the last write said `online`."
    ),
)
async def camera_health(
    session: SessionDep, manager: ManagerUser, compound_id: CompoundScope
) -> CameraHealthResponse:
    return await cv_service.camera_health(session, compound_id)


@router.get(
    "/real-mode",
    response_model=RealModeStatus,
    summary="Prove the deployment is running real detections",
    description=(
        "Returns the vision mode, loaded models, barrier driver and camera counts. "
        "`real_detections_only` is true only when CV_MODE=real and no demo camera is "
        "feeding the pipeline."
    ),
)
async def real_mode_status(
    session: SessionDep, manager: ManagerUser, compound_id: CompoundScope
) -> RealModeStatus:
    return await cv_service.real_mode_status(session, compound_id)


@router.post(
    "/cameras/{camera_id}/test",
    response_model=CameraProbeResponse,
    summary="Test a camera stream end-to-end",
    description=(
        "Opens the configured RTSP/USB source, reads a few frames, stores a preview "
        "and records the result on the camera row. Use it right after saving a new "
        "camera to confirm the URL, credentials and exposure are correct."
    ),
)
async def test_camera(
    camera_id: uuid.UUID, session: SessionDep, manager: ManagerUser
) -> CameraProbeResponse:
    camera = await camera_service.get(session, camera_id)
    gate = await gate_service.get(session, camera.gate_id)
    enforce_compound(manager, gate.compound_id)
    result = await camera_service.probe(session, camera)
    payload = result.as_dict()
    payload["hint"] = _probe_hint(result)
    return CameraProbeResponse.model_validate(payload)


@router.get(
    "/cameras/{camera_id}/snapshot",
    summary="Grab one live frame from a camera",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}},
    description=(
        "Returns a single JPEG frame straight from the camera. Used by the dashboard to "
        "preview a stream without opening the full video pipeline."
    ),
)
async def camera_snapshot(
    camera_id: uuid.UUID, session: SessionDep, manager: ManagerUser
) -> Response:
    camera = await camera_service.get(session, camera_id)
    gate = await gate_service.get(session, camera.gate_id)
    enforce_compound(manager, gate.compound_id)
    image = await camera_service.snapshot(camera)
    return Response(content=image, media_type="image/jpeg")


def _probe_hint(result: object) -> str | None:
    """Turn a failed probe into an actionable next step."""
    ok = getattr(result, "ok", False)
    if ok:
        return None
    error = str(getattr(result, "error", "") or "")
    lowered = error.lower()
    if "401" in lowered or "unauthori" in lowered or "auth" in lowered:
        return (
            "The camera rejected the credentials. Verify the RTSP user/password and that "
            "the camera allows RTSP (many vendors disable it by default)."
        )
    if "timed out" in lowered or "timeout" in lowered:
        return (
            "Connection timed out. Check that the API/CV host can reach the camera IP "
            "(same VLAN, no client isolation) and that the port is 554."
        )
    if "refused" in lowered or "unreachable" in lowered or "no route" in lowered:
        return (
            "The host is unreachable. Ping the camera IP from the server that runs the CV "
            "worker, then confirm the stream path (e.g. /Streaming/Channels/101 for Hikvision)."
        )
    if "usb" in lowered or "index" in lowered:
        return "USB index not present. List devices with `v4l2-ctl --list-devices` (Linux)."
    return (
        "Check the full URL including the stream path and credentials, then re-run the test. "
        "See docs/real-deployment.md → Troubleshooting."
    )


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
