"""Blacklist entries and face embeddings."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    JSONType,
    TimestampMixin,
    UTCDateTime,
    UUIDPrimaryKeyMixin,
    as_utc,
    utcnow,
)
from app.models.enums import BlacklistEntryType, BlacklistReason, EmbeddingSource
from app.models.types import enum_column

if TYPE_CHECKING:
    from app.models.compound import Compound
    from app.models.people import Resident, Visitor
    from app.models.user import User  # noqa: F401 - mapper registration


class BlacklistEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A plate, face or person explicitly forbidden from entering."""

    __tablename__ = "blacklist_entries"
    __table_args__ = (
        Index("ix_blacklist_compound_type", "compound_id", "entry_type", "is_active"),
        Index("ix_blacklist_plate", "plate_normalized"),
    )

    compound_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("compounds.id", ondelete="CASCADE"), index=True, nullable=False
    )
    entry_type: Mapped[BlacklistEntryType] = mapped_column(
        enum_column(BlacklistEntryType), default=BlacklistEntryType.PLATE, nullable=False
    )
    plate_number: Mapped[str | None] = mapped_column(String(20))
    plate_normalized: Mapped[str | None] = mapped_column(String(20))
    resident_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("residents.id", ondelete="CASCADE"), index=True
    )
    visitor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("visitors.id", ondelete="CASCADE"), index=True
    )
    face_embedding_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("face_embeddings.id", ondelete="SET NULL")
    )
    person_name: Mapped[str | None] = mapped_column(String(150))
    national_id: Mapped[str | None] = mapped_column(String(32))
    reason: Mapped[BlacklistReason] = mapped_column(
        enum_column(BlacklistReason), default=BlacklistReason.SECURITY, nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    compound: Mapped[Compound] = relationship()
    resident: Mapped[Resident | None] = relationship(back_populates="blacklist_entries", lazy="joined")
    visitor: Mapped[Visitor | None] = relationship(lazy="joined")

    def is_currently_active(self, at: datetime | None = None) -> bool:
        """Return ``True`` when the entry is active and not expired."""
        if not self.is_active:
            return False
        if self.expires_at is None:
            return True
        return as_utc(self.expires_at) > as_utc(at or utcnow())

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Blacklist {self.entry_type} plate={self.plate_number} active={self.is_active}>"


class FaceEmbedding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A stored InsightFace embedding (512 floats) for a person."""

    __tablename__ = "face_embeddings"
    __table_args__ = (
        Index("ix_face_embeddings_compound_active", "compound_id", "is_active"),
        Index("ix_face_embeddings_resident", "resident_id"),
    )

    compound_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("compounds.id", ondelete="CASCADE"), index=True, nullable=False
    )
    resident_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("residents.id", ondelete="CASCADE")
    )
    visitor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("visitors.id", ondelete="CASCADE")
    )
    embedding: Mapped[list[float]] = mapped_column(JSONType, nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, default=512, nullable=False)
    model_name: Mapped[str] = mapped_column(String(64), default="buffalo_l", nullable=False)
    quality: Mapped[float | None] = mapped_column(Float)
    image_url: Mapped[str | None] = mapped_column(String(500))
    source: Mapped[EmbeddingSource] = mapped_column(
        enum_column(EmbeddingSource), default=EmbeddingSource.ENROLLMENT, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    compound: Mapped[Compound] = relationship()
    resident: Mapped[Resident | None] = relationship(back_populates="face_embeddings", lazy="joined")
    visitor: Mapped[Visitor | None] = relationship(lazy="joined")

    def as_dict(self) -> dict[str, Any]:
        """Serialise the embedding for the vision gallery loader."""
        return {
            "id": str(self.id),
            "resident_id": str(self.resident_id) if self.resident_id else None,
            "visitor_id": str(self.visitor_id) if self.visitor_id else None,
            "embedding": self.embedding,
            "model_name": self.model_name,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FaceEmbedding resident={self.resident_id} dim={self.dimension}>"
