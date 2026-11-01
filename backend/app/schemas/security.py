"""Blacklist and face enrollment schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, Field, model_validator

from app.models.enums import BlacklistEntryType, BlacklistReason, EmbeddingSource
from app.schemas.common import ORMModel
from app.schemas.people import ResidentBrief


class BlacklistBase(BaseModel):
    entry_type: BlacklistEntryType = BlacklistEntryType.PLATE
    plate_number: str | None = Field(default=None, max_length=20)
    resident_id: uuid.UUID | None = None
    visitor_id: uuid.UUID | None = None
    person_name: str | None = Field(default=None, max_length=150)
    national_id: str | None = Field(default=None, max_length=32)
    reason: BlacklistReason = BlacklistReason.SECURITY
    description: str | None = None
    is_active: bool = True
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_entry(self) -> Self:
        if self.entry_type == BlacklistEntryType.PLATE and not self.plate_number:
            raise ValueError("plate_number is required for plate blacklist entries")
        if self.entry_type == BlacklistEntryType.PERSON and not (
            self.resident_id or self.national_id or self.person_name
        ):
            raise ValueError("Provide resident_id, national_id or person_name for a person entry")
        return self


class BlacklistCreate(BlacklistBase):
    compound_id: uuid.UUID


class BlacklistUpdate(BaseModel):
    plate_number: str | None = Field(default=None, max_length=20)
    person_name: str | None = Field(default=None, max_length=150)
    national_id: str | None = Field(default=None, max_length=32)
    reason: BlacklistReason | None = None
    description: str | None = None
    is_active: bool | None = None
    expires_at: datetime | None = None


class BlacklistRead(ORMModel):
    id: uuid.UUID
    compound_id: uuid.UUID
    entry_type: BlacklistEntryType
    plate_number: str | None
    plate_normalized: str | None
    resident_id: uuid.UUID | None
    visitor_id: uuid.UUID | None
    face_embedding_id: uuid.UUID | None
    person_name: str | None
    national_id: str | None
    reason: BlacklistReason
    description: str | None
    is_active: bool
    expires_at: datetime | None
    created_by_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    resident: ResidentBrief | None = None


class FaceEnrollRequest(BaseModel):
    """JSON metadata accompanying a multipart face enrollment."""

    resident_id: uuid.UUID
    source: EmbeddingSource = EmbeddingSource.ENROLLMENT
    overwrite: bool = Field(
        default=False, description="Deactivate previous embeddings for this resident"
    )


class FaceEmbeddingRead(ORMModel):
    id: uuid.UUID
    compound_id: uuid.UUID
    resident_id: uuid.UUID | None
    visitor_id: uuid.UUID | None
    dimension: int
    model_name: str
    quality: float | None
    image_url: str | None
    source: EmbeddingSource
    is_active: bool
    created_at: datetime
    updated_at: datetime
    resident: ResidentBrief | None = None
    similarity_to_existing: float | None = None


class FaceMatchResult(BaseModel):
    """Result of a face comparison (enrollment quality feedback)."""

    matched: bool
    resident_id: uuid.UUID | None = None
    similarity: float
    threshold: float


class FaceGalleryInfo(BaseModel):
    """Summary of the face gallery used by the CV engine."""

    total_embeddings: int
    active_embeddings: int
    enrolled_residents: int
    model_name: str
    threshold: float


class FaceQualityIssue(BaseModel):
    """One enrollment check result."""

    code: str
    message: str
    severity: str
    hint: str | None = None


class FaceQualityResponse(BaseModel):
    """Enrollment pre-flight report returned to the dashboard."""

    passed: bool
    score: float
    face_count: int
    width: int
    height: int
    face_ratio: float
    blur: float
    brightness: float
    duplicate_similarity: float | None = None
    issues: list[FaceQualityIssue] = Field(default_factory=list)
    thresholds: dict[str, Any] = Field(default_factory=dict)


class FacePruneRequest(BaseModel):
    """Request to deactivate surplus embeddings in a compound gallery."""

    compound_id: uuid.UUID
    max_per_resident: int | None = Field(default=None, ge=1, le=10)
    dry_run: bool = False
