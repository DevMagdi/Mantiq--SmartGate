"""Real-time event bus.

GateVision publishes domain events (new detection, access decision, camera
status) to every connected WebSocket client.  Heavily used deployments run the
CV runner as a separate process, so a Redis pub/sub bridge is supported.  When
Redis is disabled the bus degrades gracefully to a single-process broker.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """A serialisable event broadcast to subscribers."""

    type: str
    payload: dict[str, Any]
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.event_id,
            "type": self.type,
            "occurred_at": self.occurred_at.isoformat(),
            "payload": self.payload,
        }


class EventBus(ABC):
    """Abstract publish/subscribe interface."""

    @abstractmethod
    async def publish(self, event: StreamEvent) -> None:
        """Publish an event to every subscriber."""

    @abstractmethod
    def subscribe(self) -> AsyncIterator[StreamEvent]:
        """Return an async iterator of events for a single client."""

    @abstractmethod
    async def start(self) -> None:
        """Start background resources (no-op for in-memory buses)."""

    @abstractmethod
    async def stop(self) -> None:
        """Release background resources."""


class InMemoryEventBus(EventBus):
    """Process-local fan-out bus based on bounded queues."""

    def __init__(self, queue_size: int = 500) -> None:
        self._subscribers: set[asyncio.Queue[StreamEvent]] = set()
        self._queue_size = queue_size
        self._lock = asyncio.Lock()

    async def publish(self, event: StreamEvent) -> None:
        async with self._lock:
            subscribers = list(self._subscribers)
        for queue in subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Slow consumer: drop one stale event to keep real-time latency.
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(event)
                logger.warning("Slow websocket subscriber, dropping oldest event")

    async def subscribe(self) -> AsyncIterator[StreamEvent]:
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue(maxsize=self._queue_size)
        async with self._lock:
            self._subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                self._subscribers.discard(queue)

    async def start(self) -> None:  # pragma: no cover - nothing to start
        return None

    async def stop(self) -> None:
        async with self._lock:
            self._subscribers.clear()


class RedisEventBus(InMemoryEventBus):
    """Fan-out bus with a Redis pub/sub bridge for multi-process deployments."""

    def __init__(self) -> None:
        super().__init__(queue_size=1000)
        self._redis: Any | None = None
        self._listener: asyncio.Task[None] | None = None
        self._seen: set[str] = set()

    async def start(self) -> None:
        from redis.asyncio import Redis  # imported lazily to keep SQLite-only setups light

        self._redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        await self._redis.ping()
        self._listener = asyncio.create_task(self._listen(), name="redis-event-listener")
        logger.info("Redis event bridge connected", extra={"ctx_channel": settings.REDIS_EVENT_CHANNEL})

    async def publish(self, event: StreamEvent) -> None:
        # Always fan out locally first so the publishing process is never blocked.
        await super().publish(event)
        if self._redis is not None:
            try:
                await self._redis.publish(settings.REDIS_EVENT_CHANNEL, json.dumps(event.to_dict()))
            except Exception as exc:  # pragma: no cover - depends on external service
                logger.warning("Failed to publish event to Redis: %s", exc)

    async def _listen(self) -> None:  # pragma: no cover - requires Redis
        assert self._redis is not None
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(settings.REDIS_EVENT_CHANNEL)
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    raw = json.loads(message["data"])
                    event = StreamEvent(
                        type=raw["type"],
                        payload=raw.get("payload", {}),
                        event_id=raw.get("id", uuid.uuid4().hex),
                        occurred_at=datetime.fromisoformat(raw["occurred_at"]),
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    logger.warning("Discarding malformed bus message: %s", exc)
                    continue
                if event.event_id in self._seen:
                    continue
                self._seen.add(event.event_id)
                if len(self._seen) > 5000:
                    self._seen = set(list(self._seen)[-1000:])
                await InMemoryEventBus.publish(self, event)
        except asyncio.CancelledError:  # pragma: no cover
            raise
        except Exception as exc:  # pragma: no cover
            logger.error("Redis subscription failed: %s", exc)
        finally:
            with contextlib.suppress(Exception):
                await pubsub.close()

    async def stop(self) -> None:
        if self._listener is not None:
            self._listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener
            self._listener = None
        if self._redis is not None:
            with contextlib.suppress(Exception):
                await self._redis.aclose()
            self._redis = None
        await super().stop()


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Return the process-wide event bus singleton."""
    global _bus
    if _bus is None:
        _bus = RedisEventBus() if settings.REDIS_ENABLED else InMemoryEventBus()
    return _bus


async def shutdown_event_bus() -> None:
    """Stop and clear the global bus (used on application shutdown)."""
    global _bus
    if _bus is not None:
        await _bus.stop()
        _bus = None


async def publish_event(event_type: str, payload: dict[str, Any]) -> None:
    """Convenience helper to publish a typed event."""
    await get_event_bus().publish(StreamEvent(type=event_type, payload=payload))
