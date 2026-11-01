"""Authentication and user management schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import UserRole
from app.schemas.common import ORMModel


class LoginRequest(BaseModel):
    """JSON credentials login."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenPair(BaseModel):
    """Issued JWT pair plus the authenticated principal."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds")
    user: "UserRead"


class RefreshRequest(BaseModel):
    """Exchange a refresh token for a new token pair."""

    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _strength(cls, value: str) -> str:
        has_letter = any(ch.isalpha() for ch in value)
        has_digit = any(ch.isdigit() for ch in value)
        if not (has_letter and has_digit):
            raise ValueError("Password must contain at least one letter and one digit")
        return value


class UserBase(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=150)
    phone: str | None = Field(default=None, max_length=32)
    role: UserRole = UserRole.RESIDENT
    is_active: bool = True


class UserCreate(UserBase):
    """Admin payload to create a user account."""

    password: str = Field(min_length=8, max_length=128)
    compound_id: uuid.UUID | None = None

    @field_validator("password")
    @classmethod
    def _strength(cls, value: str) -> str:
        if not (any(ch.isalpha() for ch in value) and any(ch.isdigit() for ch in value)):
            raise ValueError("Password must contain at least one letter and one digit")
        return value


class UserUpdate(BaseModel):
    """Partial user update; password changes go through a dedicated endpoint."""

    email: EmailStr | None = None
    full_name: str | None = Field(default=None, min_length=2, max_length=150)
    phone: str | None = Field(default=None, max_length=32)
    role: UserRole | None = None
    is_active: bool | None = None
    compound_id: uuid.UUID | None = None


class UserRead(ORMModel):
    """Public user representation."""

    id: uuid.UUID
    email: EmailStr
    full_name: str
    phone: str | None
    role: UserRole
    is_active: bool
    compound_id: uuid.UUID | None
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime
    resident_id: uuid.UUID | None = Field(
        default=None, description="Resident profile linked to this account, if any"
    )

    @classmethod
    def from_user(cls, user: object) -> "UserRead":
        """Build a response including the linked resident id."""
        model = cls.model_validate(user)
        profile = getattr(user, "resident_profile", None)
        model.resident_id = getattr(profile, "id", None) if profile else None
        return model


class UserBrief(ORMModel):
    """Compact user representation for nested payloads."""

    id: uuid.UUID
    full_name: str
    email: EmailStr
    role: UserRole


class UserProfile(UserRead):
    """Extended profile for the authenticated user."""

    model_config = ConfigDict(from_attributes=True)


class AdminPasswordReset(BaseModel):
    """Administrator driven password reset."""

    new_password: str = Field(min_length=8, max_length=128)


class LoginAudit(BaseModel):
    """Login response metadata."""

    model_config = ConfigDict(extra="ignore")

    user: UserRead
    issued_at: datetime


TokenPair.model_rebuild()
