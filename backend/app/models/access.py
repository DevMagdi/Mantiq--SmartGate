"""Detection events and access logs: the audit trail of the gate."""

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
    utcnow,
)
from app.models.enums import (
    AccessDecision,
    AccessDirection,
    AccessMethod,
    DetectionType,
)
from app.models.types import enum_column

if TYPE_CHECKING:
    from app.models.compound import Camera, Compound, Gate
    from app.models.people import Permit, Resident, Visitor
    from app.models.user import User
    from app.models.vehicle import Vehicle


class AccessLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable record of one access decision at a gate."""

    __tablename__ = "access_logs"
    __table_args__ = (
        Index("ix_access_logs_compound_time", "compound_id", "occurred_at"),
        Index("ix_access_logs_gate_time", "gate_id", "occurred_at"),
        Index("ix_access_logs_plate_time", "plate_normalized", "occurred_at"),
        Index("ix_access_logs_decision", "decision"),
    )

    compound_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("compounds.id", ondelete="CASCADE"), nullable=False
    )
    gate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gates.id", ondelete="RESTRICT"), nullable=False
    )
    camera_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cameras.id", ondelete="SET NULL")
    )
    direction: Mapped[AccessDirection] = mapped_column(
        enum_column(AccessDirection), default=AccessDirection.ENTRY, nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, nullable=False, index=True
    )
    decision: Mapped[AccessDecision] = mapped_column(enum_column(AccessDecision), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    access_method: Mapped[AccessMethod] = mapped_column(
        enum_column(AccessMethod), default=AccessMethod.PLATE, nullable=False
    )

    plate_number: Mapped[str | None] = mapped_column(String(20))
    plate_normalized: Mapped[str | None] = mapped_column(String(20))
    plate_confidence: Mapped[float | None] = mapped_column(Float)
    face_similarity: Mapped[float | None] = mapped_column(Float)

    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vehicles.id", ondelete="SET NULL")
    )
    resident_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("residents.id", ondelete="SET NULL")
    )
    visitor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("visitors.id", ondelete="SET NULL")
    )
    permit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("permits.id", ondelete="SET NULL")
    )

    snapshot_url: Mapped[str | None] = mapped_column(String(500))
    face_snapshot_url: Mapped[str | None] = mapped_column(String(500))
    gate_opened: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    is_overridden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    override_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    override_reason: Mapped[str | None] = mapped_column(String(255))
    overridden_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    notes: Mapped[str | None] = mapped_column(Text)

    compound: Mapped[Compound] = relationship()
    gate: Mapped[Gate] = relationship(back_populates="access_logs", lazy="joined")
    camera: Mapped[Camera | None] = relationship(lazy="joined")
    vehicle: Mapped[Vehicle | None] = relationship(back_populates="access_logs", lazy="joined")
    resident: Mapped[Resident | None] = relationship(lazy="joined")
    visitor: Mapped[Visitor | None] = relationship(back_populates="access_logs", lazy="joined")
    permit: Mapped[Permit | None] = relationship(back_populates="access_logs", lazy="joined")
    override_by: Mapped[User | None] = relationship(foreign_keys=[override_by_id], lazy="joined")
    detection_event: Mapped[DetectionEvent | None] = relationship(
        back_populates="access_log", uselist=False
    )

    @property
    def plate_display(self) -> str | None:
        """Return the plate as captured (falls back to the normalised form)."""
        return self.plate_number or self.plate_normalized

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AccessLog {self.decision} plate={self.plate_number} at={self.occurred_at}>"


class DetectionEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Raw computer-vision detection captured at a camera."""

    __tablename__ = "detection_events"
    __table_args__ = (
        Index("ix_detection_events_compound_time", "compound_id", "occurred_at"),
        Index("ix_detection_events_gate_time", "gate_id", "occurred_at"),
        Index("ix_detection_events_plate", "plate_text"),
        Index("ix_detection_events_decision", "decision"),
    )

    compound_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("compounds.id", ondelete="CASCADE"), nullable=False
    )
    gate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gates.id", ondelete="RESTRICT"), nullable=False
    )
    camera_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cameras.id", ondelete="SET NULL"), index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, nullable=False, index=True
    )
    event_type: Mapped[DetectionType] = mapped_column(
        enum_column(DetectionType), default=DetectionType.PLATE, nullable=False
    )

    plate_text: Mapped[str | None] = mapped_column(String(20))
    plate_confidence: Mapped[float | None] = mapped_column(Float)
    plate_bbox: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    plate_snapshot_url: Mapped[str | None] = mapped_column(String(500))
    face_snapshot_url: Mapped[str | None] = mapped_column(String(500))
    face_detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    face_matched: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    face_similarity: Mapped[float | None] = mapped_column(Float)
    matched_resident_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("residents.id", ondelete="SET NULL")
    )
    face_embedding_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("face_embeddings.id", ondelete="SET NULL")
    )

    matched_vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vehicles.id", ondelete="SET NULL")
    )
    decision: Mapped[AccessDecision] = mapped_column(enum_column(AccessDecision), nullable=False)
    decision_reason: Mapped[str | None] = mapped_column(String(255))
    access_log_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("access_logs.id", ondelete="SET NULL"), index=True
    )
    vision_engine: Mapped[str] = mapped_column(String(64), default="pipeline", nullable=False)
    processing_ms: Mapped[int | None] = mapped_column(Integer)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)

    compound: Mapped[Compound] = relationship()
    gate: Mapped[Gate] = relationship(back_populates="detection_events", lazy="joined")
    camera: Mapped[Camera | None] = relationship(back_populates="detection_events", lazy="joined")
    matched_resident: Mapped[Resident | None] = relationship(lazy="joined")
    matched_vehicle: Mapped[Vehicle | None] = relationship(lazy="joined")
    access_log: Mapped[AccessLog | None] = relationship(
        back_populates="detection_event", foreign_keys=[access_log_id], lazy="joined"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DetectionEvent {self.event_type} plate={self.plate_text} decision={self.decision}>"
