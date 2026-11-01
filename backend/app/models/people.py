"""Residents, visitors and temporary permits."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin, as_utc, utcnow
from app.models.enums import (
    PermitStatus,
    PermitType,
    ResidentRelationship,
    ResidentStatus,
    VisitorStatus,
)
from app.models.types import enum_column

if TYPE_CHECKING:
    from app.models.access import AccessLog
    from app.models.compound import Compound, Unit
    from app.models.security import BlacklistEntry, FaceEmbedding
    from app.models.user import User
    from app.models.vehicle import Vehicle


class Resident(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A person living in a unit, optionally linked to a login account."""

    __tablename__ = "residents"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_residents_user_id"),
        Index("ix_residents_compound_status", "compound_id", "status"),
        Index("ix_residents_national_id", "national_id"),
    )

    compound_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("compounds.id", ondelete="CASCADE"), index=True, nullable=False
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("units.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    national_id: Mapped[str | None] = mapped_column(String(32))
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(255))
    role_in_unit: Mapped[ResidentRelationship] = mapped_column(
        enum_column(ResidentRelationship), default=ResidentRelationship.OWNER, nullable=False
    )
    status: Mapped[ResidentStatus] = mapped_column(
        enum_column(ResidentStatus), default=ResidentStatus.ACTIVE, nullable=False
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    move_in_date: Mapped[datetime | None] = mapped_column(Date)
    move_out_date: Mapped[datetime | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    compound: Mapped[Compound] = relationship()
    unit: Mapped[Unit] = relationship(back_populates="residents", lazy="joined")
    user: Mapped[User | None] = relationship(back_populates="resident_profile", lazy="joined")
    vehicles: Mapped[list[Vehicle]] = relationship(
        back_populates="resident", cascade="all, delete-orphan"
    )
    face_embeddings: Mapped[list[FaceEmbedding]] = relationship(
        back_populates="resident", cascade="all, delete-orphan"
    )
    permits_as_host: Mapped[list[Permit]] = relationship(
        back_populates="host_resident", foreign_keys="Permit.host_resident_id"
    )
    blacklist_entries: Mapped[list[BlacklistEntry]] = relationship(back_populates="resident")

    @property
    def is_active(self) -> bool:
        """Return ``True`` when the resident may access the compound."""
        return self.status == ResidentStatus.ACTIVE

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Resident {self.full_name} unit={self.unit_id}>"


class Visitor(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A guest expected at (or currently inside) the compound."""

    __tablename__ = "visitors"
    __table_args__ = (
        Index("ix_visitors_compound_status", "compound_id", "status"),
        Index("ix_visitors_phone", "phone"),
    )

    compound_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("compounds.id", ondelete="CASCADE"), index=True, nullable=False
    )
    host_unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("units.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    host_resident_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("residents.id", ondelete="SET NULL"), index=True
    )
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    national_id: Mapped[str | None] = mapped_column(String(32))
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(255))
    company: Mapped[str | None] = mapped_column(String(150))
    purpose: Mapped[str | None] = mapped_column(String(255))
    photo_url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[VisitorStatus] = mapped_column(
        enum_column(VisitorStatus), default=VisitorStatus.PENDING, nullable=False
    )
    expected_arrival: Mapped[datetime | None] = mapped_column(UTCDateTime())
    actual_arrival: Mapped[datetime | None] = mapped_column(UTCDateTime())
    actual_departure: Mapped[datetime | None] = mapped_column(UTCDateTime())
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    host_unit: Mapped[Unit] = relationship(back_populates="visitors", lazy="joined")
    host_resident: Mapped[Resident | None] = relationship(lazy="joined")
    permits: Mapped[list[Permit]] = relationship(
        back_populates="visitor", cascade="all, delete-orphan"
    )
    access_logs: Mapped[list[AccessLog]] = relationship(back_populates="visitor")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Visitor {self.full_name} status={self.status}>"


class Permit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Time-bound authorisation for a visitor/contractor vehicle or person."""

    __tablename__ = "permits"
    __table_args__ = (
        UniqueConstraint("permit_code", name="uq_permits_permit_code"),
        Index("ix_permits_compound_status", "compound_id", "status"),
        Index("ix_permits_window", "start_at", "end_at"),
    )

    compound_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("compounds.id", ondelete="CASCADE"), index=True, nullable=False
    )
    visitor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("visitors.id", ondelete="CASCADE"), index=True, nullable=False
    )
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vehicles.id", ondelete="SET NULL"), index=True
    )
    host_unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("units.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    host_resident_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("residents.id", ondelete="SET NULL"), index=True
    )
    permit_code: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    permit_type: Mapped[PermitType] = mapped_column(
        enum_column(PermitType), default=PermitType.VISITOR, nullable=False
    )
    status: Mapped[PermitStatus] = mapped_column(
        enum_column(PermitStatus), default=PermitStatus.ACTIVE, nullable=False
    )
    start_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    end_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    max_entries: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    entries_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    issued_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    revoked_reason: Mapped[str | None] = mapped_column(String(255))
    revoked_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    visitor: Mapped[Visitor] = relationship(back_populates="permits", lazy="joined")
    vehicle: Mapped[Vehicle | None] = relationship(back_populates="permits", lazy="joined")
    host_unit: Mapped[Unit] = relationship(
        back_populates="visitor_permits", foreign_keys=[host_unit_id], lazy="joined"
    )
    host_resident: Mapped[Resident | None] = relationship(
        back_populates="permits_as_host", foreign_keys=[host_resident_id]
    )
    access_logs: Mapped[list[AccessLog]] = relationship(back_populates="permit")

    @property
    def vehicle_plate(self) -> str | None:
        """Plate authorised by this permit, if a vehicle is linked."""
        return self.vehicle.plate_number if self.vehicle is not None else None

    def is_currently_valid(self, at: datetime | None = None) -> bool:
        """Return ``True`` when the permit can authorise entry right now."""
        moment = as_utc(at or utcnow())
        if self.status != PermitStatus.ACTIVE:
            return False
        if not (as_utc(self.start_at) <= moment <= as_utc(self.end_at)):
            return False
        return self.entries_used < self.max_entries

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Permit {self.permit_code} status={self.status}>"
