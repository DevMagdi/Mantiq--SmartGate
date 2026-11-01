"""Async SQLAlchemy engine/session factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _engine_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {"echo": settings.DATABASE_ECHO, "future": True}
    if settings.is_sqlite:
        # SQLite connections are not thread-safe; a null pool keeps things simple.
        kwargs["poolclass"] = NullPool
        kwargs["connect_args"] = {"timeout": 30}
    else:
        kwargs["pool_size"] = settings.DATABASE_POOL_SIZE
        kwargs["max_overflow"] = settings.DATABASE_MAX_OVERFLOW
        kwargs["pool_pre_ping"] = True
        kwargs["pool_recycle"] = 1800
    return kwargs


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs())
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(), expire_on_commit=False, autoflush=False, class_=AsyncSession
        )
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Provide a transactional session scope for background jobs/services."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped session."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Dispose the engine (application shutdown / tests)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


async def check_database() -> bool:
    """Return ``True`` when the database answers a trivial query."""
    from sqlalchemy import text

    try:
        async with get_engine().connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # pragma: no cover - depends on environment
        logger.error("Database health check failed: %s", exc)
        return False
