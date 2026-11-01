"""MQTT barrier driver.

Publishes barrier commands to an MQTT broker (Mosquitto, EMQX, HiveMQ, ...).
This is the usual integration path for industrial controllers and ESP32 relay
boards that already speak MQTT.

Topic template defaults to ``gatevision/{gate}/command``; the placeholders
``{gate}`` and ``{compound}`` are substituted per command. ``simulate=true``
(default) logs the publish without a broker so the feature can be tested in
staging without hardware.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import uuid
from typing import Any

from app.core.logging import get_logger
from app.cv.actuators.base import ActuatorResult, BarrierActuator, _Timer

logger = get_logger(__name__)


class MqttActuator(BarrierActuator):
    """Publishes JSON barrier commands to an MQTT topic."""

    driver = "mqtt"
    name = "mqtt"

    def __init__(
        self,
        *,
        host: str = "localhost",
        port: int = 1883,
        topic: str = "gatevision/{gate}/command",
        qos: int = 1,
        username: str | None = None,
        password: str | None = None,
        tls: bool = False,
        client_id: str = "gatevision-api",
        simulate: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.topic = topic
        self.qos = max(0, min(2, qos))
        self.username = username
        self.password = password
        self.tls = tls
        self.client_id = client_id
        self.simulate = simulate
        self._commands = 0
        self._failures = 0
        self._last_error: str | None = None

    # ------------------------------------------------------------------ publish
    def _topic_for(self, gate_code: str) -> str:
        try:
            return self.topic.format(gate=gate_code, compound="default")
        except (KeyError, IndexError, ValueError):
            return f"gatevision/{gate_code}/command"

    def _publish_blocking(self, topic: str, body: bytes) -> dict[str, Any]:
        import paho.mqtt.client as mqtt  # lazy: optional CV/IoT dependency

        try:  # paho-mqtt >= 2.0 requires the callback API version
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2, client_id=f"{self.client_id}-{uuid.uuid4().hex[:6]}"
            )
        except (AttributeError, TypeError):  # pragma: no cover - paho 1.x
            client = mqtt.Client(client_id=f"{self.client_id}-{uuid.uuid4().hex[:6]}")
        if self.username:
            client.username_pw_set(self.username, self.password)
        if self.tls:
            import ssl

            client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
        client.connect(self.host, self.port, keepalive=10)
        info = client.publish(topic, payload=body, qos=self.qos)
        info.wait_for_publish(timeout=5)
        rc = getattr(info, "rc", None)
        client.disconnect()
        return {"rc": rc, "topic": topic}

    async def send(self, action: str, gate_code: str, reason: str) -> ActuatorResult:
        timer = _Timer()
        self._commands += 1
        topic = self._topic_for(gate_code)
        payload = {
            "event_id": str(uuid.uuid4()),
            "gate": gate_code,
            "action": action,
            "reason": reason,
            "issued_at": dt.datetime.now(dt.UTC).isoformat(),
            "source": "gatevision",
        }
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

        if self.simulate:
            logger.info(
                "MQTT (simulated) publish %s -> %s:%s qos=%s action=%s",
                topic,
                self.host,
                self.port,
                self.qos,
                action,
            )
            return ActuatorResult(
                accepted=True,
                driver=self.driver,
                detail=f"MQTT publish simulated on {topic} ({action} {gate_code})",
                latency_ms=timer.elapsed_ms(),
                extra={"topic": topic, "simulated": True},
            )

        try:
            info = await asyncio.to_thread(self._publish_blocking, topic, body)
        except ImportError:
            self._failures += 1
            self._last_error = "paho-mqtt is not installed"
            return ActuatorResult(
                accepted=False,
                driver=self.driver,
                detail=(
                    "MQTT driver needs paho-mqtt: pip install 'paho-mqtt>=2.0' "
                    "or set barrier.mqtt.simulate=true"
                ),
                latency_ms=timer.elapsed_ms(),
                error="dependency_missing",
            )
        except Exception as exc:
            self._failures += 1
            self._last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("MQTT publish failed for %s: %s", gate_code, exc)
            return ActuatorResult(
                accepted=False,
                driver=self.driver,
                detail=f"MQTT publish to {topic} failed: {self._last_error}",
                latency_ms=timer.elapsed_ms(),
                error=self._last_error,
                extra={"topic": topic},
            )

        self._last_error = None
        return ActuatorResult(
            accepted=True,
            driver=self.driver,
            detail=f"MQTT published {action} to {topic} (qos {self.qos})",
            latency_ms=timer.elapsed_ms(),
            extra={"topic": topic, "rc": info.get("rc")},
        )

    def health(self) -> dict[str, Any]:
        return {
            "driver": self.driver,
            "ready": True,
            "simulated": self.simulate,
            "broker": f"{self.host}:{self.port}",
            "tls": self.tls,
            "topic": self.topic,
            "qos": self.qos,
            "commands": self._commands,
            "failures": self._failures,
            "last_error": self._last_error,
        }

    def describe(self) -> dict[str, Any]:
        return {
            "driver": self.driver,
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "topic": self.topic,
            "qos": self.qos,
            "tls": self.tls,
            "username": self.username,
            "simulated": self.simulate,
        }


__all__ = ["MqttActuator"]
