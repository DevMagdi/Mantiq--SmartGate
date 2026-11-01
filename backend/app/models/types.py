"""Reusable SQLAlchemy column helpers for enums."""

from __future__ import annotations

from enum import Enum
from typing import Any, TypeVar

from sqlalchemy import Enum as SAEnum

E = TypeVar("E", bound=Enum)


def enum_column(enum_cls: type[E], length: int = 32) -> SAEnum:
    """Create a portable, value-storing enum column type.

    ``native_enum=False`` keeps SQLite and PostgreSQL schemas identical and
    stores the lowercase enum *values* (never the Python member names).
    """

    def _values(enum_type: type[Enum]) -> list[str]:
        return [str(member.value) for member in enum_type]

    return SAEnum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=_values,
        validate_strings=True,
        name=f"{enum_cls.__name__.lower()}_enum",
    )


def enum_values(enum_cls: type[Enum]) -> list[str]:
    """Return the stored values for an enum (used by API filters)."""
    return [str(member.value) for member in enum_cls]


def coerce_enum(enum_cls: type[E], value: Any) -> E:  # pragma: no cover - defensive helper
    """Coerce an arbitrary value into an enum member."""
    if isinstance(value, enum_cls):
        return value
    return enum_cls(str(value))
