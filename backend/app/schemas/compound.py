"""Compound, gate, camera and unit schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import (
    CameraSourceType,
    CameraStatus,
    GateDirection,
    GateStatus,
    UnitStatus,
    UnitType,
)
from app.schemas.common import ORMModel


class CompoundCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    code: str = Field(min_length=2, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    address: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    country: str = Field(default="EG", min_length=2, max_length=2)
    timezone: str = Field(default="Africa/Cairo", max_length=64)
    contact_email: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=32)
    logo_url: str | None = Field(default=None, max_length=500)
    is_active: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)

    @field_validator("code")
    @classmethod
    def _upper_code(cls, value: str) -> str:
        return value.strip().upper()


class CompoundUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    address: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    timezone: str | None = Field(default=None, max_length=64)
    contact_email: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=32)
    logo_url: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None
    settings: dict[str, Any] | None = None


class VisionPolicyUpdate(BaseModel):
    """Per-compound CV thresholds (all optional; defaults come from the env)."""

    plate_confidence_threshold: float | None = Field(default=None, ge=0.05, le=0.95)
    ocr_min_confidence: float | None = Field(default=None, ge=0.05, le=0.98)
    face_similarity_threshold: float | None = Field(default=None, ge=0.2, le=0.85)
    face_min_quality: float | None = Field(default=None, ge=0, le=100)
    face_min_resolution: int | None = Field(default=None, ge=80, le=2000)
    face_min_blur: float | None = Field(default=None, ge=0, le=500)
    face_min_brightness: float | None = Field(default=None, ge=0, le=254)
    face_max_brightness: float | None = Field(default=None, ge=1, le=255)
    face_min_face_ratio: float | None = Field(default=None, ge=0.01, le=0.9)
    max_embeddings_per_resident: int | None = Field(default=None, ge=1, le=10)
    duplicate_similarity_threshold: float | None = Field(default=None, ge=0.5, le=0.995)
    reject_duplicate_enrollment: bool | None = None


class AccessPolicyUpdate(BaseModel):
    """Per-compound decision-engine switches."""

    auto_open_barrier: bool | None = None
    allow_face_only_entry: bool | None = None
    unknown_vehicle_decision: Literal["unknown", "review", "deny"] | None = None
    require_face_for_vehicle: bool | None = None
    exit_grace_minutes: int | None = Field(default=None, ge=0, le=720)
    allow_blacklist_exit: bool | None = None
    allow_visitor_exit_after_expiry: bool | None = None


class WebhookBarrierUpdate(BaseModel):
    url: str | None = Field(default=None, max_length=500)
    secret: str | None = Field(default=None, max_length=255)
    timeout_seconds: float | None = Field(default=None, ge=0.5, le=30)
    retries: int | None = Field(default=None, ge=0, le=5)
    verify_tls: bool | None = None


class MqttBarrierUpdate(BaseModel):
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    topic: str | None = Field(default=None, max_length=255)
    qos: int | None = Field(default=None, ge=0, le=2)
    username: str | None = Field(default=None, max_length=120)
    password: str | None = Field(default=None, max_length=255)
    tls: bool | None = None
    simulate: bool | None = None


class GpioBarrierUpdate(BaseModel):
    open_pin: int | None = Field(default=None, ge=1, le=40)
    close_pin: int | None = Field(default=None, ge=1, le=40)
    hold_pin: int | None = Field(default=None, ge=1, le=40)
    active_high: bool | None = None
    pulse_seconds: float | None = Field(default=None, ge=0.05, le=10)
    backend: Literal["gpiozero", "rpi_gpio"] | None = None
    simulate: bool | None = None


class BarrierPolicyUpdate(BaseModel):
    """Barrier transport configuration."""

    driver: Literal["simulator", "webhook", "mqtt", "gpio"] | None = None
    simulator_latency_ms: int | None = Field(default=None, ge=0, le=5000)
    simulator_failure_rate: float | None = Field(default=None, ge=0, le=1)
    webhook: WebhookBarrierUpdate | None = None
    mqtt: MqttBarrierUpdate | None = None
    gpio: GpioBarrierUpdate | None = None


class CompoundSettingsUpdate(BaseModel):
    """Partial update of ``compound.settings`` (unknown keys are preserved)."""

    vision: VisionPolicyUpdate | None = None
    access: AccessPolicyUpdate | None = None
    barrier: BarrierPolicyUpdate | None = None


class CompoundSettingsRead(BaseModel):
    """Effective settings plus the fully resolved policy."""

    compound_id: uuid.UUID
    raw: dict[str, Any]
    effective: dict[str, Any]
    defaults: dict[str, Any]


class CompoundRead(ORMModel):
    id: uuid.UUID
    name: str
    code: str
    address: str | None
    city: str | None
    country: str
    timezone: str
    contact_email: str | None
    contact_phone: str | None
    logo_url: str | None
    is_active: bool
    settings: dict[str, Any]
    created_at: datetime

    @field_validator("settings", mode="after")
    @classmethod
    def _mask_secrets(cls, value: dict[str, Any]) -> dict[str, Any]:
        from app.services.compound_policy import mask_secrets_in_settings

        return mask_secrets_in_settings(value)

    updated_at: datetime


class CompoundBrief(ORMModel):
    id: uuid.UUID
    name: str
    code: str


class CameraBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    source_type: CameraSourceType = CameraSourceType.RTSP
    source_url: str = Field(min_length=1, max_length=500)
    is_active: bool = True
    fps_limit: float = Field(default=5.0, gt=0, le=30)
    position: str = Field(default="front", max_length=32)
    notes: str | None = None

    @field_validator("source_url")
    @classmethod
    def _validate_source(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Camera source is required")
        return value


class CameraCreate(CameraBase):
    gate_id: uuid.UUID


class CameraUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    source_type: CameraSourceType | None = None
    source_url: str | None = Field(default=None, min_length=1, max_length=500)
    is_active: bool | None = None
    fps_limit: float | None = Field(default=None, gt=0, le=30)
    position: str | None = Field(default=None, max_length=32)
    notes: str | None = None
    status: CameraStatus | None = None


class CameraRead(ORMModel):
    id: uuid.UUID
    gate_id: uuid.UUID
    name: str
    source_type: CameraSourceType
    source_url: str
    is_active: bool
    status: CameraStatus
    fps_limit: float
    position: str
    resolution: str | None = None
    last_frame_at: datetime | None
    last_error: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class CameraBrief(ORMModel):
    id: uuid.UUID
    name: str
    status: CameraStatus
    position: str


class GateBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    direction: GateDirection = GateDirection.BIDIRECTIONAL
    status: GateStatus = GateStatus.ONLINE
    location: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    is_active: bool = True

    @field_validator("code")
    @classmethod
    def _upper_code(cls, value: str) -> str:
        return value.strip().upper()


class GateCreate(GateBase):
    compound_id: uuid.UUID


class GateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    direction: GateDirection | None = None
    status: GateStatus | None = None
    location: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    is_active: bool | None = None


class GateRead(ORMModel):
    id: uuid.UUID
    compound_id: uuid.UUID
    name: str
    code: str
    direction: GateDirection
    status: GateStatus
    location: str | None
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    cameras: list[CameraBrief] = Field(default_factory=list)


class GateBrief(ORMModel):
    id: uuid.UUID
    name: str
    code: str
    direction: GateDirection
    status: GateStatus


class UnitBase(BaseModel):
    building: str = Field(min_length=1, max_length=50)
    unit_number: str = Field(min_length=1, max_length=20)
    floor: int = Field(default=0, ge=-5, le=200)
    unit_type: UnitType = UnitType.APARTMENT
    status: UnitStatus = UnitStatus.VACANT
    bedrooms: int | None = Field(default=None, ge=0, le=50)
    area_sqm: float | None = Field(default=None, gt=0, le=100000)
    notes: str | None = None


class UnitCreate(UnitBase):
    compound_id: uuid.UUID | None = Field(
        default=None, description="Optional guard: the compound comes from the URL path"
    )


class UnitUpdate(BaseModel):
    building: str | None = Field(default=None, min_length=1, max_length=50)
    unit_number: str | None = Field(default=None, min_length=1, max_length=20)
    floor: int | None = Field(default=None, ge=-5, le=200)
    unit_type: UnitType | None = None
    status: UnitStatus | None = None
    bedrooms: int | None = Field(default=None, ge=0, le=50)
    area_sqm: float | None = Field(default=None, gt=0, le=100000)
    notes: str | None = None


class UnitRead(ORMModel):
    id: uuid.UUID
    compound_id: uuid.UUID
    building: str
    unit_number: str
    floor: int
    unit_type: UnitType
    status: UnitStatus
    bedrooms: int | None
    area_sqm: float | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    label: str


class UnitBrief(ORMModel):
    id: uuid.UUID
    building: str
    unit_number: str
    label: str
