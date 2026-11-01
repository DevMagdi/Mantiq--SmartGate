"""Pagination helpers shared by list services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.schemas.common import Page

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class PageParams:
    """Validated pagination parameters."""

    page: int = 1
    page_size: int = settings.DEFAULT_PAGE_SIZE
    sort_by: str = "created_at"
    sort_dir: str = "desc"

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def page_params(
    page: int = 1, page_size: int = settings.DEFAULT_PAGE_SIZE, sort_dir: str = "desc", sort_by: str = "created_at"
) -> PageParams:
    """Clamp pagination inputs into safe bounds."""
    page = max(1, page)
    page_size = min(max(1, page_size), settings.MAX_PAGE_SIZE)
    direction = "desc" if str(sort_dir).lower() != "asc" else "asc"
    return PageParams(page=page, page_size=page_size, sort_by=sort_by, sort_dir=direction)


async def count_rows(session: AsyncSession, stmt: Select[tuple[T]]) -> int:
    """Return the row count of a select statement (without ordering)."""
    subquery = stmt.order_by(None).options().subquery()
    total = await session.scalar(select(func.count()).select_from(subquery))
    return int(total or 0)


def apply_sort(stmt: Select[tuple[T]], column: object, direction: str) -> Select[tuple[T]]:
    """Apply ASC/DESC ordering on a model column."""
    return stmt.order_by(column.desc() if direction == "desc" else column.asc())


def build_page(items: list[T], total: int, params: PageParams) -> Page[T]:
    """Wrap items in the generic page envelope."""
    return Page.create(items=items, total=total, page=params.page, page_size=params.page_size)
