"""Detection and access log schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    AccessDecision,
    AccessDirection,
    AccessMethod,
    DetectionType,
)
from app.schemas.common import ORMModel
from app.schemas.compound import CameraBrief, GateBrief
from app.schemas.people import PermitBrief, ResidentBrief, VisitorBrief
from app.schemas.vehicle import VehicleBrief


class AccessLogRead(ORMModel):
    id: uuid.UUID
    compound_id: uuid.UUID
    gate_id: uuid.UUID
    camera_id: uuid.UUID | None
    direction: AccessDirection
    occurred_at: datetime
    decision: AccessDecision
    reason_code: str
    reason: str
    access_method: AccessMethod
    plate_number: str | None
    plate_confidence: float | None
    face_similarity: float | None
    vehicle_id: uuid.UUID | None
    resident_id: uuid.UUID | None
    visitor_id: uuid.UUID | None
    permit_id: uuid.UUID | None
    snapshot_url: str | None
    face_snapshot_url: str | None
    gate_opened: bool
    is_overridden: bool
    override_by_id: uuid.UUID | None
    override_reason: str | None
    overridden_at: datetime | None
    notes: str | None
    created_at: datetime
    gate: GateBrief | None = None
    camera: CameraBrief | None = None
    vehicle: VehicleBrief | None = None
    resident: ResidentBrief | None = None
    visitor: VisitorBrief | None = None
    permit: PermitBrief | None = None


class DetectionEventRead(ORMModel):
    id: uuid.UUID
    compound_id: uuid.UUID
    gate_id: uuid.UUID
    camera_id: uuid.UUID | None
    occurred_at: datetime
    event_type: DetectionType
    plate_text: str | None
    plate_confidence: float | None
    plate_bbox: dict[str, Any] | None
    plate_snapshot_url: str | None
    face_snapshot_url: str | None
    face_detected: bool
    face_matched: bool
    face_similarity: float | None
    matched_resident_id: uuid.UUID | None
    matched_vehicle_id: uuid.UUID | None
    decision: AccessDecision
    decision_reason: str | None
    access_log_id: uuid.UUID | None
    vision_engine: str
    processing_ms: int | None
    raw_payload: dict[str, Any]
    created_at: datetime
    gate: GateBrief | None = None
    camera: CameraBrief | None = None
    matched_resident: ResidentBrief | None = None
    matched_vehicle: VehicleBrief | None = None


class ManualOverrideRequest(BaseModel):
    """Security officer override of an access decision."""

    decision: AccessDecision = Field(description="Final decision after review")
    reason: str = Field(min_length=3, max_length=255)
    open_gate: bool = Field(default=False, description="Command the barrier to open")
    notes: str | None = Field(default=None, max_length=1000)


class ManualEntryRequest(BaseModel):
    """Log an access decision made entirely by a security officer."""

    gate_id: uuid.UUID
    decision: AccessDecision = AccessDecision.ALLOW
    direction: AccessDirection = AccessDirection.ENTRY
    plate_number: str | None = Field(default=None, max_length=20)
    reason: str = Field(default="Manual gate operation", min_length=3, max_length=255)
    notes: str | None = Field(default=None, max_length=1000)
    open_gate: bool = True


class GateCommandRequest(BaseModel):
    """Direct barrier command issued from the dashboard."""

    action: str = Field(pattern="^(open|close|hold)$")
    reason: str = Field(default="Dashboard command", min_length=3, max_length=255)


class GateCommandResult(BaseModel):
    gate_id: uuid.UUID
    action: str
    accepted: bool
    detail: str
    driver: str = "simulator"
    latency_ms: int = 0
    command_id: str | None = None


class ActuatorCommandRead(BaseModel):
    """One journaled barrier command."""

    id: str
    occurred_at: str
    gate_code: str
    gate_id: str | None = None
    compound_id: str | None = None
    action: str
    driver: str
    accepted: bool
    latency_ms: int = 0
    attempts: int = 1
    detail: str
    actor: str
    reason: str
    error: str | None = None
    external_status: int | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ActuatorStatus(BaseModel):
    """Barrier driver configuration, health and recent commands."""

    compound_id: uuid.UUID | None = None
    compound_name: str | None = None
    configured: bool = False
    driver: str = "simulator"
    name: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    health: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    journal: dict[str, Any] = Field(default_factory=dict)
    recent_commands: list[ActuatorCommandRead] = Field(default_factory=list)


class ActuatorStatusResponse(BaseModel):
    compounds: list[ActuatorStatus] = Field(default_factory=list)
    journal: dict[str, Any] = Field(default_factory=dict)


class ActuatorTestRequest(BaseModel):
    gate_id: uuid.UUID
    action: str = Field(default="open", pattern="^(open|close|hold)$")


class VisionAnalyzeResponse(BaseModel):
    """Result of analysing an uploaded image through the CV pipeline."""

    plate_text: str | None = None
    plate_confidence: float | None = None
    plate_snapshot_url: str | None = None
    face_detected: bool = False
    face_matched: bool = False
    face_similarity: float | None = None
    matched_resident_id: uuid.UUID | None = None
    decision: AccessDecision
    reason_code: str
    reason: str
    access_method: AccessMethod
    detection_event_id: uuid.UUID | None = None
    access_log_id: uuid.UUID | None = None
    processing_ms: int | None = None
    model_config = ConfigDict(json_schema_extra={"description": "Vision analysis outcome"})


class VisionPipelineStatus(BaseModel):
    mode: str
    plate_detector: str
    ocr_engine: str
    face_engine: str
    engine_ready: bool
    models_loaded: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    face_gallery_size: int = 0
    similarity_threshold: float
