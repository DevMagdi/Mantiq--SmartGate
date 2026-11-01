"""Realtime WebSocket event tests."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

API = "/api/v1"


def _token(client: TestClient, email: str, password: str) -> str:
    response = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    return response.json()["access_token"]


def test_websocket_requires_auth(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"{API}/ws/events") as ws:
            ws.receive_json()
    assert exc.value.code == 1008

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"{API}/ws/events?token=invalid.token.value") as ws:
            ws.receive_json()


def test_websocket_greeting_and_ping(client: TestClient) -> None:
    token = _token(client, "officer@gatevision.app", "Officer@12345")
    with client.websocket_connect(f"{API}/ws/events?token={token}") as ws:
        greeting = ws.receive_json()
        assert greeting["type"] == "connected"
        payload = greeting["payload"]
        assert payload["user"]["role"] == "security_officer"
        assert payload["compound_id"]
        assert payload["heartbeat_seconds"] == 25

        ws.send_text("ping")
        pong = ws.receive_json()
        assert pong["type"] == "pong"
        assert "server_time" in pong["payload"]


def test_websocket_receives_detection_events(
    client: TestClient, demo: dict[str, Any]
) -> None:
    token = _token(client, "officer@gatevision.app", "Officer@12345")
    gate_id = demo["gate"]["id"]
    with client.websocket_connect(
        f"{API}/ws/events?token={token}&gate_id={gate_id}"
    ) as ws:
        ws.receive_json()  # connected greeting
        created = client.post(
            f"{API}/access-logs/manual",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "gate_id": gate_id,
                "decision": "allow",
                "direction": "entry",
                "plate_number": "WS 4242",
                "reason": "WebSocket integration test",
            },
        )
        assert created.status_code == 201

        event = _next_event(ws, "detection.created")
        assert event["payload"]["plate_text"] == "WS 4242"
        assert event["payload"]["decision"] == "allow"
        assert event["payload"]["access_log_id"] == created.json()["id"]
        assert event["payload"]["gate_id"] == gate_id


def test_websocket_filters_other_gates(
    client: TestClient, demo: dict[str, Any]
) -> None:
    token = _token(client, "officer@gatevision.app", "Officer@12345")
    with client.websocket_connect(
        f"{API}/ws/events?token={token}&gate_id={demo['gate']['id']}"
    ) as ws:
        ws.receive_json()
        response = client.post(
            f"{API}/access-logs/manual",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "gate_id": demo["exit_gate"]["id"],
                "decision": "allow",
                "direction": "exit",
                "reason": "Should be filtered out",
            },
        )
        assert response.status_code == 201
        ws.send_text("ping")
        for _ in range(6):
            message = ws.receive_json()
            assert message["type"] != "detection.created"
            if message["type"] == "pong":
                break


def test_resident_cannot_subscribe_to_another_compound(client: TestClient) -> None:
    token = _token(client, "ahmed@gatevision.app", "Resident@12345")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"{API}/ws/events?token={token}&compound_id=00000000-0000-0000-0000-000000000000"
        ) as ws:
            ws.receive_json()


def _next_event(ws: Any, event_type: str, limit: int = 10) -> dict[str, Any]:
    for _ in range(limit):
        message = json.loads(ws.receive_text())
        if message.get("type") == event_type:
            return message
    raise AssertionError(f"Did not receive event {event_type}")
