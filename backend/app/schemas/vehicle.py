"""Vehicle schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.enums import VehicleStatus, VehicleType
from app.schemas.common import ORMModel
from app.schemas.people import ResidentBrief


def normalize_plate(value: str) -> str:
    """Normalise a plate for storage and matching.

    Uppercases, converts Arabic-Indic digits to ASCII and strips every
    separator so that ``"أ ب ج ١٢٣"`` and ``"ABJ-123"`` compare equal.
    """
    arabic_digits = "٠١٢٣٤٥٦٧٨٩"
    translation = {ord(ch): str(idx) for idx, ch in enumerate(arabic_digits)}
    cleaned = value.translate(translation).upper()
    return "".join(ch for ch in cleaned if ch.isalnum())


class VehicleBase(BaseModel):
    plate_number: str = Field(min_length=3, max_length=20)
    make: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=64)
    color: str | None = Field(default=None, max_length=32)
    year: int | None = Field(default=None, ge=1950, le=2100)
    vehicle_type: VehicleType = VehicleType.CAR
    status: VehicleStatus = VehicleStatus.ACTIVE
    sticker_number: str | None = Field(default=None, max_length=32)
    notes: str | None = None

    @field_validator("plate_number")
    @classmethod
    def _clean_plate(cls, value: str) -> str:
        value = value.strip()
        if len(normalize_plate(value)) < 3:
            raise ValueError("Plate number must contain at least 3 characters")
        return value


class VehicleCreate(VehicleBase):
    compound_id: uuid.UUID
    resident_id: uuid.UUID | None = None


class VehicleUpdate(BaseModel):
    plate_number: str | None = Field(default=None, min_length=3, max_length=20)
    resident_id: uuid.UUID | None = None
    make: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=64)
    color: str | None = Field(default=None, max_length=32)
    year: int | None = Field(default=None, ge=1950, le=2100)
    vehicle_type: VehicleType | None = None
    status: VehicleStatus | None = None
    sticker_number: str | None = Field(default=None, max_length=32)
    notes: str | None = None

    @field_validator("plate_number")
    @classmethod
    def _clean_plate(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if len(normalize_plate(value)) < 3:
            raise ValueError("Plate number must contain at least 3 characters")
        return value


class VehicleRead(ORMModel):
    id: uuid.UUID
    compound_id: uuid.UUID
    resident_id: uuid.UUID | None
    plate_number: str
    plate_normalized: str
    make: str | None
    model: str | None
    color: str | None
    year: int | None
    vehicle_type: VehicleType
    status: VehicleStatus
    sticker_number: str | None
    is_inside: bool
    last_seen_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    resident: ResidentBrief | None = None


class VehicleBrief(ORMModel):
    id: uuid.UUID
    plate_number: str
    make: str | None
    model: str | None
    color: str | None
    status: VehicleStatus
