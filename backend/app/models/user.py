"""User accounts and their link to resident profiles."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin
from app.models.enums import UserRole
from app.models.types import enum_column

if TYPE_CHECKING:
    from app.models.compound import Compound
    from app.models.people import Resident


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An authenticated principal (admin, security officer or resident)."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    compound_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("compounds.id", ondelete="SET NULL"), index=True, nullable=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32))
    role: Mapped[UserRole] = mapped_column(
        enum_column(UserRole), default=UserRole.RESIDENT, nullable=False, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    compound: Mapped[Compound | None] = relationship(back_populates="users", lazy="joined")
    resident_profile: Mapped[Resident | None] = relationship(
        back_populates="user", uselist=False, foreign_keys="Resident.user_id"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<User {self.email} role={self.role}>"
