"""Shared schema primitives: pagination, messaging and health."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    """Base model for ORM-backed responses."""

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class Page(BaseModel, Generic[T]):
    """A paginated collection."""

    items: list[T]
    total: int = Field(description="Total number of matching rows")
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    pages: int = Field(ge=0)

    @classmethod
    def create(cls, items: list[T], total: int, page: int, page_size: int) -> "Page[T]":
        pages = (total + page_size - 1) // page_size if page_size else 0
        return cls(items=items, total=total, page=page, page_size=page_size, pages=pages)


class Message(BaseModel):
    """Simple status message."""

    message: str
    detail: str | None = None


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    """Consistent error envelope returned by every endpoint."""

    error: ErrorBody


class HealthResponse(BaseModel):
    """Liveness/readiness payload."""

    status: str
    version: str
    environment: str
    database: bool
    redis: bool
    cv_mode: str
    timestamp: datetime


class SortParams(BaseModel):
    """Common sorting parameters."""

    sort_by: str = "created_at"
    sort_dir: str = Field(default="desc", pattern="^(asc|desc)$")


class BulkDeleteRequest(BaseModel):
    ids: list[Any] = Field(min_length=1, max_length=500)
