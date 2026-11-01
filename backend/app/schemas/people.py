"""Resident, visitor and permit schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Self

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.models.enums import (
    PermitStatus,
    PermitType,
    ResidentRelationship,
    ResidentStatus,
    VisitorStatus,
)
from app.schemas.common import ORMModel
from app.schemas.compound import UnitBrief


class ResidentBase(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    national_id: str | None = Field(default=None, max_length=32)
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    role_in_unit: ResidentRelationship = ResidentRelationship.OWNER
    status: ResidentStatus = ResidentStatus.ACTIVE
    is_primary: bool = False
    move_in_date: date | None = None
    move_out_date: date | None = None
    notes: str | None = None


class ResidentCreate(ResidentBase):
    compound_id: uuid.UUID
    unit_id: uuid.UUID
    user_id: uuid.UUID | None = Field(
        default=None, description="Optional existing user account to link"
    )
    create_account: bool = Field(
        default=False,
        description="Create a resident portal account using the provided email",
    )
    account_password: str | None = Field(default=None, min_length=8, max_length=128)

    @model_validator(mode="after")
    def _validate_account(self) -> Self:
        if self.create_account:
            if not self.email:
                raise ValueError("email is required when create_account is true")
            if not self.account_password:
                raise ValueError("account_password is required when create_account is true")
        return self


class ResidentUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=150)
    national_id: str | None = Field(default=None, max_length=32)
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    unit_id: uuid.UUID | None = None
    role_in_unit: ResidentRelationship | None = None
    status: ResidentStatus | None = None
    is_primary: bool | None = None
    move_in_date: date | None = None
    move_out_date: date | None = None
    notes: str | None = None


class ResidentRead(ORMModel):
    id: uuid.UUID
    compound_id: uuid.UUID
    unit_id: uuid.UUID
    user_id: uuid.UUID | None
    full_name: str
    national_id: str | None
    phone: str | None
    email: str | None
    role_in_unit: ResidentRelationship
    status: ResidentStatus
    is_primary: bool
    move_in_date: date | None
    move_out_date: date | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    unit: UnitBrief | None = None
    vehicle_count: int = 0
    face_count: int = 0


class ResidentBrief(ORMModel):
    id: uuid.UUID
    full_name: str
    phone: str | None
    status: ResidentStatus


class VisitorBase(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    national_id: str | None = Field(default=None, max_length=32)
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    company: str | None = Field(default=None, max_length=150)
    purpose: str | None = Field(default=None, max_length=255)
    host_unit_id: uuid.UUID
    host_resident_id: uuid.UUID | None = None
    expected_arrival: datetime | None = None
    notes: str | None = None


class VisitorCreate(VisitorBase):
    compound_id: uuid.UUID


class VisitorUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=150)
    national_id: str | None = Field(default=None, max_length=32)
    phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    company: str | None = Field(default=None, max_length=150)
    purpose: str | None = Field(default=None, max_length=255)
    host_unit_id: uuid.UUID | None = None
    host_resident_id: uuid.UUID | None = None
    expected_arrival: datetime | None = None
    notes: str | None = None
    status: VisitorStatus | None = None


class VisitorRead(ORMModel):
    id: uuid.UUID
    compound_id: uuid.UUID
    host_unit_id: uuid.UUID
    host_resident_id: uuid.UUID | None
    full_name: str
    national_id: str | None
    phone: str | None
    email: str | None
    company: str | None
    purpose: str | None
    photo_url: str | None
    status: VisitorStatus
    expected_arrival: datetime | None
    actual_arrival: datetime | None
    actual_departure: datetime | None
    notes: str | None
    created_by_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    host_unit: UnitBrief | None = None
    active_permit_count: int = 0


class VisitorBrief(ORMModel):
    id: uuid.UUID
    full_name: str
    phone: str | None
    status: VisitorStatus


class PermitBase(BaseModel):
    permit_type: PermitType = PermitType.VISITOR
    start_at: datetime
    end_at: datetime
    max_entries: int = Field(default=1, ge=1, le=100)
    vehicle_id: uuid.UUID | None = None
    host_unit_id: uuid.UUID
    host_resident_id: uuid.UUID | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _validate_window(self) -> Self:
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self


class PermitCreate(PermitBase):
    visitor_id: uuid.UUID
    vehicle_plate: str | None = Field(
        default=None,
        max_length=20,
        description="Plate to authorise; created on the fly when not yet registered",
    )


class PermitUpdate(BaseModel):
    permit_type: PermitType | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    max_entries: int | None = Field(default=None, ge=1, le=100)
    vehicle_id: uuid.UUID | None = None
    notes: str | None = None


class PermitRevoke(BaseModel):
    reason: str = Field(min_length=3, max_length=255)


class PermitRead(ORMModel):
    id: uuid.UUID
    compound_id: uuid.UUID
    visitor_id: uuid.UUID
    vehicle_id: uuid.UUID | None
    host_unit_id: uuid.UUID
    host_resident_id: uuid.UUID | None
    permit_code: str
    permit_type: PermitType
    status: PermitStatus
    start_at: datetime
    end_at: datetime
    max_entries: int
    entries_used: int
    notes: str | None
    revoked_at: datetime | None
    revoked_reason: str | None
    created_at: datetime
    updated_at: datetime
    visitor: VisitorBrief | None = None
    host_unit: UnitBrief | None = None
    vehicle_plate: str | None = None


class PermitBrief(ORMModel):
    id: uuid.UUID
    permit_code: str
    permit_type: PermitType
    status: PermitStatus
    start_at: datetime
    end_at: datetime
    entries_used: int
    max_entries: int
