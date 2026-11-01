"""Vehicle registry linked to residents and permits."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin
from app.models.enums import VehicleStatus, VehicleType
from app.models.types import enum_column

if TYPE_CHECKING:
    from app.models.access import AccessLog
    from app.models.compound import Compound
    from app.models.people import Permit, Resident


class Vehicle(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A registered vehicle; the plate is unique within its compound."""

    __tablename__ = "vehicles"
    __table_args__ = (
        UniqueConstraint("compound_id", "plate_normalized", name="uq_vehicles_plate"),
        Index("ix_vehicles_resident_status", "resident_id", "status"),
        Index("ix_vehicles_plate_normalized", "plate_normalized"),
    )

    compound_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("compounds.id", ondelete="CASCADE"), index=True, nullable=False
    )
    resident_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("residents.id", ondelete="CASCADE"), index=True
    )
    plate_number: Mapped[str] = mapped_column(String(20), nullable=False)
    plate_normalized: Mapped[str] = mapped_column(String(20), nullable=False)
    make: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(64))
    color: Mapped[str | None] = mapped_column(String(32))
    year: Mapped[int | None] = mapped_column(Integer)
    vehicle_type: Mapped[VehicleType] = mapped_column(
        enum_column(VehicleType), default=VehicleType.CAR, nullable=False
    )
    status: Mapped[VehicleStatus] = mapped_column(
        enum_column(VehicleStatus), default=VehicleStatus.ACTIVE, nullable=False
    )
    sticker_number: Mapped[str | None] = mapped_column(String(32))
    is_inside: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    notes: Mapped[str | None] = mapped_column(Text)

    compound: Mapped[Compound] = relationship()
    resident: Mapped[Resident | None] = relationship(back_populates="vehicles", lazy="joined")
    permits: Mapped[list[Permit]] = relationship(back_populates="vehicle")
    access_logs: Mapped[list[AccessLog]] = relationship(back_populates="vehicle")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Vehicle {self.plate_number} status={self.status}>"
