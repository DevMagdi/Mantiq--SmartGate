"""Compound, gate, camera and unit models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, JSONType, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin, utcnow
from app.models.enums import (
    CameraSourceType,
    CameraStatus,
    GateDirection,
    GateStatus,
    UnitStatus,
    UnitType,
)
from app.models.types import enum_column

if TYPE_CHECKING:
    from app.models.access import AccessLog, DetectionEvent
    from app.models.people import Permit, Resident, Visitor
    from app.models.security import BlacklistEntry, FaceEmbedding  # noqa: F401 - mapper registration
    from app.models.user import User


class Compound(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A residential compound / real-estate project (tenant boundary)."""

    __tablename__ = "compounds"
    __table_args__ = (UniqueConstraint("code", name="uq_compounds_code"),)

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    address: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(2), default="EG", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Africa/Cairo", nullable=False)
    contact_email: Mapped[str | None] = mapped_column(String(255))
    contact_phone: Mapped[str | None] = mapped_column(String(32))
    logo_url: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)

    gates: Mapped[list[Gate]] = relationship(back_populates="compound", cascade="all, delete-orphan")
    units: Mapped[list[Unit]] = relationship(back_populates="compound", cascade="all, delete-orphan")
    users: Mapped[list[User]] = relationship(back_populates="compound")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Compound {self.code} {self.name}>"


class Gate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A physical gate (entry / exit / bidirectional) inside a compound."""

    __tablename__ = "gates"
    __table_args__ = (UniqueConstraint("compound_id", "code", name="uq_gates_compound_code"),)

    compound_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("compounds.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[GateDirection] = mapped_column(
        enum_column(GateDirection), default=GateDirection.BIDIRECTIONAL, nullable=False
    )
    status: Mapped[GateStatus] = mapped_column(
        enum_column(GateStatus), default=GateStatus.ONLINE, nullable=False
    )
    location: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    compound: Mapped[Compound] = relationship(back_populates="gates")
    cameras: Mapped[list[Camera]] = relationship(
        back_populates="gate", cascade="all, delete-orphan", lazy="selectin"
    )
    access_logs: Mapped[list[AccessLog]] = relationship(back_populates="gate")
    detection_events: Mapped[list[DetectionEvent]] = relationship(back_populates="gate")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Gate {self.code} {self.direction}>"


class Camera(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A camera attached to a gate."""

    __tablename__ = "cameras"
    __table_args__ = (UniqueConstraint("gate_id", "name", name="uq_cameras_gate_name"),)

    gate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gates.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    source_type: Mapped[CameraSourceType] = mapped_column(
        enum_column(CameraSourceType), default=CameraSourceType.RTSP, nullable=False
    )
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[CameraStatus] = mapped_column(
        enum_column(CameraStatus), default=CameraStatus.OFFLINE, nullable=False
    )
    fps_limit: Mapped[float] = mapped_column(Float, default=5.0, nullable=False)
    resolution: Mapped[str | None] = mapped_column(String(32))
    last_frame_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_error: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    position: Mapped[str] = mapped_column(String(32), default="front", nullable=False)

    gate: Mapped[Gate] = relationship(back_populates="cameras")
    detection_events: Mapped[list[DetectionEvent]] = relationship(back_populates="camera")

    def mark_online(self) -> None:
        """Record a healthy frame read."""
        self.status = CameraStatus.ONLINE
        self.last_frame_at = utcnow()
        self.last_error = None

    def mark_error(self, message: str) -> None:
        """Record a stream failure."""
        self.status = CameraStatus.ERROR
        self.last_error = message[:2000]

    def mark_offline(self) -> None:
        """Record a deliberately stopped stream."""
        self.status = CameraStatus.OFFLINE


class Unit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A residential unit inside a compound."""

    __tablename__ = "units"
    __table_args__ = (
        UniqueConstraint("compound_id", "building", "unit_number", name="uq_units_location"),
    )

    compound_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("compounds.id", ondelete="CASCADE"), index=True, nullable=False
    )
    building: Mapped[str] = mapped_column(String(50), nullable=False)
    unit_number: Mapped[str] = mapped_column(String(20), nullable=False)
    floor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unit_type: Mapped[UnitType] = mapped_column(
        enum_column(UnitType), default=UnitType.APARTMENT, nullable=False
    )
    status: Mapped[UnitStatus] = mapped_column(
        enum_column(UnitStatus), default=UnitStatus.VACANT, nullable=False
    )
    bedrooms: Mapped[int | None] = mapped_column(Integer)
    area_sqm: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)

    compound: Mapped[Compound] = relationship(back_populates="units")
    residents: Mapped[list[Resident]] = relationship(back_populates="unit")
    visitor_permits: Mapped[list[Permit]] = relationship(
        back_populates="host_unit", foreign_keys="Permit.host_unit_id"
    )
    visitors: Mapped[list[Visitor]] = relationship(back_populates="host_unit")

    @property
    def label(self) -> str:
        """Human readable unit label (``B12-304``)."""
        return f"{self.building}-{self.unit_number}"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Unit {self.label}>"
