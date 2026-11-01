"""End-to-end proof that a real decision really moves the barrier.

These tests drive the *production* path with no camera and no mock engine:

    VisionResult -> AccessDecisionEngine (DB rules) -> GateController
                 -> WebhookActuator -> HTTP POST on the wire

A local HTTP server plays the role of the barrier controller, so the assertions
are about bytes actually leaving the process: method, JSON body and HMAC
signature. The last test proves the opposite direction: a denied detection must
not fire a command at all.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.cv.types import BoundingBox, PlateReading, VisionResult
from app.db.session import session_scope
from app.models.compound import Gate
from app.models.enums import AccessDecision, VehicleStatus
from app.models.vehicle import Vehicle
from app.services.detection_service import DetectionService

API = "/api/v1"


class _Controller(BaseHTTPRequestHandler):
    """Minimal barrier controller: records every command it receives."""

    received: list[dict[str, Any]] = []
    status_code = 200

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        type(self).received.append(
            {
                "path": self.path,
                "body": body,
                "headers": dict(self.headers),
                "timestamp": self.headers.get("X-GateVision-Timestamp"),
            }
        )
        self.send_response(type(self).status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, *_: Any) -> None:  # silence the test output
        return


@pytest.fixture()
def controller() -> Any:
    _Controller.received = []
    _Controller.status_code = 200
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Controller)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/relay"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _webhook_policy(client: TestClient, headers: dict[str, str], compound_id: str, url: str) -> None:
    response = client.patch(
        f"{API}/compounds/{compound_id}/settings",
        headers=headers,
        json={
            "barrier": {
                "driver": "webhook",
                "webhook": {"url": url, "secret": "controller-secret", "retries": 0,
                            "timeout_seconds": 2},
            }
        },
    )
    assert response.status_code == 200, response.text


def _vision_result(plate_text: str, gate_id: uuid.UUID, confidence: float = 0.93) -> VisionResult:
    from datetime import UTC, datetime

    bbox = BoundingBox(120, 240, 380, 320)
    return VisionResult(
        plate=PlateReading(text=plate_text, confidence=confidence, bbox=bbox, engine="test-ocr"),
        face=None,
        face_match=None,
        face_embedding=None,
        plate_snapshot_url="/media/detections/plate-test.jpg",
        face_snapshot_url=None,
        processing_ms=42,
        engine="test-engine",
        captured_at=datetime.now(UTC),
        camera_id=None,
        gate_id=gate_id,
    )


async def _process(gate_id: uuid.UUID, plate_text: str) -> tuple[AccessDecision, bool, uuid.UUID]:
    async with session_scope() as session:
        gate = await session.get(Gate, gate_id)
        assert gate is not None
        recorded = await DetectionService().process(
            session, gate=gate, camera=None, result=_vision_result(plate_text, gate_id)
        )
        return (
            recorded.decision.decision,
            recorded.access_log.gate_opened,
            recorded.access_log.id,
        )


def test_allowed_real_detection_posts_signed_webhook(
    client: TestClient, admin_headers: dict[str, str], demo: dict[str, Any], controller: str
) -> None:
    import asyncio

    compound_id = demo["compound"]["id"]
    gate_id = uuid.UUID(demo["gate"]["id"])
    _webhook_policy(client, admin_headers, compound_id, controller)

    async def _plate() -> str:
        async with session_scope() as session:
            vehicle = (
                await session.execute(
                    select(Vehicle)
                    .where(Vehicle.resident_id.is_not(None), Vehicle.status == VehicleStatus.ACTIVE)
                    .limit(1)
                )
            ).scalar_one()
            return str(vehicle.plate_number)

    plate_text = asyncio.run(_plate())
    decision, gate_opened, _ = asyncio.run(_process(gate_id, plate_text))

    assert decision == AccessDecision.ALLOW
    assert gate_opened is True
    assert _Controller.received, "an allow decision must reach the barrier controller"

    request = _Controller.received[-1]
    payload = json.loads(request["body"])
    assert payload["action"] == "open"
    assert payload["source"] == "gatevision"
    assert payload["gate"] == demo["gate"]["code"]
    assert request["path"] == "/relay"

    expected = hmac.new(
        b"controller-secret",
        f"{request['timestamp']}.".encode() + request["body"],
        hashlib.sha256,
    ).hexdigest()
    assert request["headers"]["X-GateVision-Signature"] == f"sha256={expected}"


def test_denied_detection_sends_no_command(
    client: TestClient, admin_headers: dict[str, str], demo: dict[str, Any], controller: str
) -> None:
    import asyncio

    _webhook_policy(client, admin_headers, demo["compound"]["id"], controller)

    decision, gate_opened, _ = asyncio.run(
        _process(uuid.UUID(demo["gate"]["id"]), "ZZZ 9999")
    )

    # ``unknown`` (log only) is the default; the compound can escalate it to
    # review or deny. Either way the barrier must stay closed.
    assert decision in (AccessDecision.UNKNOWN, AccessDecision.REVIEW, AccessDecision.DENY)
    assert gate_opened is False
    assert _Controller.received == [], "a refused vehicle must never open the barrier"


def test_controller_error_is_reported_as_closed_gate(
    client: TestClient, admin_headers: dict[str, str], demo: dict[str, Any], controller: str
) -> None:
    import asyncio

    _webhook_policy(client, admin_headers, demo["compound"]["id"], controller)
    _Controller.status_code = 503

    async def _plate() -> str:
        async with session_scope() as session:
            vehicle = (
                await session.execute(
                    select(Vehicle)
                    .where(Vehicle.resident_id.is_not(None), Vehicle.status == VehicleStatus.ACTIVE)
                    .limit(1)
                )
            ).scalar_one()
            return str(vehicle.plate_number)

    plate_text = asyncio.run(_plate())
    decision, gate_opened, log_id = asyncio.run(
        _process(uuid.UUID(demo["gate"]["id"]), plate_text)
    )

    # The access decision stands (the resident is allowed) but the audit trail
    # must record that the barrier did NOT open.
    assert decision == AccessDecision.ALLOW
    assert gate_opened is False
    assert log_id is not None
    assert _Controller.received, "the controller must have been called"
