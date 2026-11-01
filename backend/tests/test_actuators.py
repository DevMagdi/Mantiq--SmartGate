"""Barrier actuator drivers: webhook signatures, retries, MQTT/GPIO and API."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from typing import Any

import httpx
from starlette.testclient import TestClient

from app.cv.actuators import (
    CommandJournal,
    GpioActuator,
    MqttActuator,
    SimulatedActuator,
    WebhookActuator,
    build_actuator,
    sign_payload,
)
from app.cv.actuators.base import ActuatorResult
from app.services.compound_policy import BarrierPolicy

API = "/api/v1"


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Simulator
# --------------------------------------------------------------------------- #


def test_simulator_accepts_and_measures_latency() -> None:
    actuator = SimulatedActuator(latency_ms=5)
    result = _run(actuator.send("open", "GATE-IN", "unit test"))
    assert result.accepted is True
    assert result.driver == "simulator"
    assert result.latency_ms >= 1
    assert actuator.health()["commands"] == 1


def test_simulator_can_inject_failures_deterministically() -> None:
    actuator = SimulatedActuator(latency_ms=0, failure_rate=1.0)
    result = _run(actuator.open("GATE-IN", "always fails"))
    assert result.accepted is False
    assert result.error == "simulated_failure"
    assert actuator.health()["failures"] == 1


# --------------------------------------------------------------------------- #
# Webhook
# --------------------------------------------------------------------------- #


def _mock_transport(
    statuses: list[int], captured: list[httpx.Request]
) -> httpx.MockTransport:
    queue = list(statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        code = queue.pop(0) if queue else 200
        return httpx.Response(code, json={"ok": code < 400})

    return httpx.MockTransport(handler)


def test_webhook_signs_payload_for_controller_verification() -> None:
    captured: list[httpx.Request] = []
    actuator = WebhookActuator(
        "https://controller.local/barrier",
        secret="unit-secret",
        retry_backoff=0,
        transport=_mock_transport([200], captured),
    )
    result = _run(actuator.open("GATE-IN", "resident arrival"))

    assert result.accepted is True
    assert result.external_status == 200
    assert len(captured) == 1
    request = captured[0]
    body = request.content
    timestamp = request.headers["X-GateVision-Timestamp"]
    signature = request.headers["X-GateVision-Signature"]
    expected = hmac.new(
        b"unit-secret", timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    assert signature == f"sha256={expected}"
    assert signature == sign_payload("unit-secret", timestamp, body)
    assert request.headers["X-GateVision-Action"] == "open"
    assert request.headers["X-GateVision-Event-Id"]

    payload = json.loads(body)
    assert payload["gate"] == "GATE-IN"
    assert payload["action"] == "open"
    assert payload["reason"] == "resident arrival"
    assert payload["source"] == "gatevision"
    assert payload["issued_at"]


def test_webhook_retries_on_server_errors_then_succeeds() -> None:
    captured: list[httpx.Request] = []
    actuator = WebhookActuator(
        "https://controller.local/barrier",
        retries=2,
        retry_backoff=0,
        transport=_mock_transport([503, 502, 204], captured),
    )
    result = _run(actuator.close("GATE-OUT", "exit"))

    assert result.accepted is True
    assert result.attempts == 3
    assert result.external_status == 204
    assert len(captured) == 3


def test_webhook_does_not_retry_client_errors() -> None:
    captured: list[httpx.Request] = []
    actuator = WebhookActuator(
        "https://controller.local/barrier",
        retries=3,
        retry_backoff=0,
        transport=_mock_transport([403], captured),
    )
    result = _run(actuator.open("GATE-IN", "no permission"))

    assert result.accepted is False
    assert result.attempts == 1
    assert result.external_status == 403
    assert "HTTP 403" in result.detail
    assert len(captured) == 1
    assert actuator.health()["consecutive_failures"] == 1


def test_webhook_reports_transport_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    actuator = WebhookActuator(
        "http://127.0.0.1:9/barrier",
        retries=1,
        retry_backoff=0,
        transport=httpx.MockTransport(handler),
    )
    result = _run(actuator.hold("GATE-IN", "gridlock"))

    assert result.accepted is False
    assert result.attempts == 2
    assert "ConnectError" in (result.error or "")
    assert actuator.health()["last_error"] is not None


# --------------------------------------------------------------------------- #
# MQTT / GPIO (simulated: no broker or hardware needed)
# --------------------------------------------------------------------------- #


def test_mqtt_simulation_publishes_to_the_templated_topic() -> None:
    actuator = MqttActuator(host="broker.local", port=1883, simulate=True)
    result = _run(actuator.open("GATE-IN", "visitor"))

    assert result.accepted is True
    assert result.extra["topic"] == "gatevision/GATE-IN/command"
    assert result.extra["simulated"] is True
    assert actuator.health()["broker"] == "broker.local:1883"


def test_gpio_simulation_pulses_the_configured_pin() -> None:
    actuator = GpioActuator(open_pin=17, close_pin=27, hold_pin=None, simulate=True)
    opened = _run(actuator.open("GATE-IN", "resident"))
    held = _run(actuator.hold("GATE-IN", "slow gate"))

    assert opened.accepted is True
    assert opened.extra["pin"] == 17
    # ``hold`` falls back to the open pin when no hold pin is wired.
    assert held.extra["pin"] == 17
    assert actuator.health()["pins"] == {"open": 17, "close": 27, "hold": None}


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #


def test_factory_builds_every_driver_and_warns_on_missing_webhook_url() -> None:
    webhook, warnings = build_actuator(
        BarrierPolicy.from_mapping(
            {"driver": "webhook", "webhook": {"url": "https://ctl.local/hook"}}
        )
    )
    assert isinstance(webhook, WebhookActuator) and not warnings

    mqtt, _ = build_actuator(BarrierPolicy.from_mapping({"driver": "mqtt"}))
    assert isinstance(mqtt, MqttActuator)

    gpio, _ = build_actuator(BarrierPolicy.from_mapping({"driver": "gpio"}))
    assert isinstance(gpio, GpioActuator)

    fallback, warnings = build_actuator(BarrierPolicy.from_mapping({"driver": "webhook"}))
    assert isinstance(fallback, SimulatedActuator)
    assert warnings and "without a URL" in warnings[0]


def test_command_journal_keeps_recent_commands_and_counters() -> None:
    journal = CommandJournal(max_records=5)
    for index in range(7):
        journal.record(
            gate_code="GATE-IN",
            action="open",
            result=ActuatorResult(
                accepted=index % 2 == 0, driver="simulator", detail=f"cmd {index}"
            ),
            actor="officer@gatevision.app",
            reason=f"reason {index}",
            compound_id="compound-1",
        )
    summary = journal.summary()
    assert summary["total"] == 7
    assert summary["accepted"] == 4
    assert summary["failed"] == 3
    assert len(journal.recent(10)) == 5
    assert journal.recent(1)[0].detail == "cmd 6"
    assert journal.recent(10, compound_id="other") == []


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #


def test_actuator_status_endpoint_shows_driver_and_health(
    client: TestClient, admin_headers: dict[str, str], demo: dict[str, Any]
) -> None:
    response = client.get(f"{API}/cv/actuators", headers=admin_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["compounds"], "at least the demo compound must be listed"
    entry = body["compounds"][0]
    assert entry["driver"] in {"simulator", "webhook", "mqtt", "gpio"}
    assert entry["health"]["driver"] == entry["driver"]
    assert "journal" in body


def test_actuator_test_command_is_audited_and_switches_driver(
    client: TestClient, admin_headers: dict[str, str], demo: dict[str, Any]
) -> None:
    compound_id = demo["compound"]["id"]
    gate_id = demo["gate"]["id"]

    # Webhook pointed at a closed port: the command must fail fast and be logged.
    patched = client.patch(
        f"{API}/compounds/{compound_id}/settings",
        headers=admin_headers,
        json={
            "barrier": {
                "driver": "webhook",
                "webhook": {
                    "url": "http://127.0.0.1:9/barrier",
                    "retries": 0,
                    "timeout_seconds": 0.5,
                },
            }
        },
    )
    assert patched.status_code == 200, patched.text

    failed = client.post(
        f"{API}/cv/actuators/test",
        headers=admin_headers,
        json={"gate_id": gate_id, "action": "open"},
    )
    assert failed.status_code == 200, failed.text
    failed_body = failed.json()
    assert failed_body["accepted"] is False
    assert failed_body["driver"] == "webhook"
    assert failed_body["command_id"]

    status_response = client.get(
        f"{API}/cv/actuators?compound_id={compound_id}", headers=admin_headers
    ).json()
    entry = next(item for item in status_response["compounds"] if item["compound_id"] == compound_id)
    assert entry["driver"] == "webhook"
    assert entry["config"]["webhook"]["url"] == "http://127.0.0.1:9/barrier"
    # Secrets are masked, never returned in clear text.
    assert entry["config"]["webhook"]["secret"] in (None, "********")
    assert entry["recent_commands"], "the failed command must be journaled"
    assert entry["recent_commands"][0]["accepted"] is False
    assert entry["recent_commands"][0]["driver"] == "webhook"

    # Switching back to the simulator makes commands succeed again.
    restored = client.patch(
        f"{API}/compounds/{compound_id}/settings",
        headers=admin_headers,
        json={"barrier": {"driver": "simulator"}},
    )
    assert restored.status_code == 200, restored.text
    ok = client.post(
        f"{API}/cv/actuators/test",
        headers=admin_headers,
        json={"gate_id": gate_id, "action": "close"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["accepted"] is True
    assert ok.json()["driver"] == "simulator"

    audit = client.get(f"{API}/cv/actuators", headers=admin_headers).json()["journal"]
    assert audit["total"] >= 2
    assert audit["by_driver"].get("webhook", 0) >= 1
