"""Small async cache abstraction backed by Redis or an in-process dict."""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class Cache(ABC):
    """Key/value JSON cache."""

    @abstractmethod
    async def get(self, key: str) -> Any | None:
        """Return a cached value or ``None``."""

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Store a value with an optional TTL in seconds."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove a key."""

    @abstractmethod
    async def close(self) -> None:
        """Release connections."""


class MemoryCache(Cache):
    """Simple TTL cache for single-process deployments and tests."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}

    async def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at and expires_at < time.monotonic():
            self._store.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        ttl = settings.CACHE_TTL_SECONDS if ttl is None else ttl
        self._store[key] = (time.monotonic() + ttl if ttl > 0 else 0.0, value)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def close(self) -> None:
        self._store.clear()


class RedisCache(Cache):
    """Redis backed cache with JSON serialisation."""

    def __init__(self) -> None:
        self._client: Any | None = None

    async def _get_client(self) -> Any:
        if self._client is None:
            from redis.asyncio import Redis

            self._client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._client

    async def get(self, key: str) -> Any | None:
        try:
            raw = await (await self._get_client()).get(key)
        except Exception as exc:  # pragma: no cover
            logger.warning("Cache get failed: %s", exc)
            return None
        return json.loads(raw) if raw is not None else None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        ttl = settings.CACHE_TTL_SECONDS if ttl is None else ttl
        try:
            await (await self._get_client()).set(key, json.dumps(value), ex=ttl or None)
        except Exception as exc:  # pragma: no cover
            logger.warning("Cache set failed: %s", exc)

    async def delete(self, key: str) -> None:
        try:
            await (await self._get_client()).delete(key)
        except Exception as exc:  # pragma: no cover
            logger.warning("Cache delete failed: %s", exc)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


_cache: Cache | None = None


def get_cache() -> Cache:
    """Return the process-wide cache singleton."""
    global _cache
    if _cache is None:
        _cache = RedisCache() if settings.REDIS_ENABLED else MemoryCache()
    return _cache


async def close_cache() -> None:
    global _cache
    if _cache is not None:
        await _cache.close()
        _cache = None


async def check_redis() -> bool:
    """Ping Redis, returning ``False`` when disabled or unreachable."""
    if not settings.REDIS_ENABLED:
        return False
    from redis.asyncio import Redis

    client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await client.ping()
        return True
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.warning("Redis health check failed: %s", exc)
        return False
    finally:
        await client.aclose()
