"""WebSocket stream of real-time gate events."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.events import get_event_bus
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.db.session import session_scope
from app.models.enums import UserRole
from app.services.auth_service import auth_service

logger = get_logger(__name__)

router = APIRouter(tags=["Realtime"])

HEARTBEAT_SECONDS = 25


@router.websocket("/ws/events")
async def gate_events(
    websocket: WebSocket,
    token: str | None = Query(default=None, description="JWT access token"),
    compound_id: uuid.UUID | None = Query(default=None),
    gate_id: uuid.UUID | None = Query(default=None),
) -> None:
    """Push detections, decisions, camera status and gate commands in real time.

    Authenticate with ``?token=<access token>``. Admins see every compound by
    default; other roles are pinned to their own compound. Optional
    ``compound_id`` / ``gate_id`` query parameters narrow the stream.
    """
    if not token:
        await websocket.close(code=1008, reason="Missing token")
        return
    try:
        async with session_scope() as session:
            user, _ = await auth_service.resolve_token(session, token)
            role = user.role
            user_compound = user.compound_id
            user_name = user.full_name
            user_email = user.email
    except AppError as exc:
        await websocket.close(code=1008, reason=exc.message[:120])
        return
    except Exception:  # pragma: no cover - database unavailable
        await websocket.close(code=1011, reason="Authentication unavailable")
        return

    scope_compound = compound_id if role == UserRole.ADMIN else user_compound
    if role != UserRole.ADMIN and compound_id is not None and compound_id != user_compound:
        await websocket.close(code=1008, reason="Compound not allowed")
        return

    await websocket.accept()
    await websocket.send_json(
        {
            "type": "connected",
            "payload": {
                "user": {"name": user_name, "email": user_email, "role": str(role)},
                "compound_id": str(scope_compound) if scope_compound else None,
                "gate_id": str(gate_id) if gate_id else None,
                "server_time": datetime.now(UTC).isoformat(),
                "heartbeat_seconds": HEARTBEAT_SECONDS,
            },
        }
    )
    bus = get_event_bus()
    subscription = bus.subscribe()

    async def sender() -> None:
        async for event in subscription:
            payload = event.to_dict()
            event_compound = payload.get("payload", {}).get("compound_id")
            if scope_compound is not None and event_compound not in (None, str(scope_compound)):
                continue
            event_gate = payload.get("payload", {}).get("gate_id")
            if gate_id is not None and event_gate not in (None, str(gate_id)):
                continue
            await websocket.send_json(payload)

    async def receiver() -> None:
        while True:
            message = await websocket.receive_text()
            if message.strip().lower() == "ping":
                await websocket.send_json(
                    {"type": "pong", "payload": {"server_time": datetime.now(UTC).isoformat()}}
                )

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            await websocket.send_json(
                {"type": "ping", "payload": {"server_time": datetime.now(UTC).isoformat()}}
            )

    tasks = [
        asyncio.create_task(sender(), name="ws-sender"),
        asyncio.create_task(receiver(), name="ws-receiver"),
        asyncio.create_task(heartbeat(), name="ws-heartbeat"),
    ]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in pending:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for task in done:
            exception = task.exception()
            if exception is not None and not isinstance(exception, WebSocketDisconnect):
                logger.debug("Websocket task ended: %s", exception)
    except WebSocketDisconnect:
        pass
    finally:
        with contextlib.suppress(Exception):
            await subscription.aclose()
        logger.debug("Websocket client disconnected (%s)", user_email)
