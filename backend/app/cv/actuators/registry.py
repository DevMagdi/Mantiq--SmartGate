"""Builds and caches one barrier actuator per compound.

The actuator is rebuilt automatically when the compound's ``barrier`` policy
changes (driver, URL, credentials, pins, ...), so an operator can switch from
the simulator to a real controller from the dashboard without restarting the
API.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from typing import Any

from app.core.logging import get_logger
from app.services.compound_policy import BarrierPolicy
from app.cv.actuators.base import BarrierActuator
from app.cv.actuators.gpio import GpioActuator
from app.cv.actuators.mqtt import MqttActuator
from app.cv.actuators.simulator import SimulatedActuator
from app.cv.actuators.webhook import WebhookActuator

logger = get_logger(__name__)


def _signature(policy: BarrierPolicy) -> str:
    payload = json.dumps(policy.to_dict(mask_secrets=False), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_actuator(policy: BarrierPolicy) -> tuple[BarrierActuator, list[str]]:
    """Return an actuator for a policy plus any configuration warnings."""
    warnings: list[str] = []
    driver = policy.driver
    if driver == "webhook":
        if not policy.webhook.url:
            warnings.append("webhook driver selected without a URL; falling back to simulator")
            return SimulatedActuator(
                policy.simulator_latency_ms, policy.simulator_failure_rate
            ), warnings
        return (
            WebhookActuator(
                policy.webhook.url,
                secret=policy.webhook.secret,
                timeout=policy.webhook.timeout_seconds,
                retries=policy.webhook.retries,
                verify_tls=policy.webhook.verify_tls,
            ),
            warnings,
        )
    if driver == "mqtt":
        return (
            MqttActuator(
                host=policy.mqtt.host,
                port=policy.mqtt.port,
                topic=policy.mqtt.topic,
                qos=policy.mqtt.qos,
                username=policy.mqtt.username,
                password=policy.mqtt.password,
                tls=policy.mqtt.tls,
                client_id=policy.mqtt.client_id,
                simulate=policy.mqtt.simulate,
            ),
            warnings,
        )
    if driver == "gpio":
        return (
            GpioActuator(
                open_pin=policy.gpio.open_pin,
                close_pin=policy.gpio.close_pin,
                hold_pin=policy.gpio.hold_pin,
                active_high=policy.gpio.active_high,
                pulse_seconds=policy.gpio.pulse_seconds,
                backend=policy.gpio.backend,
                simulate=policy.gpio.simulate,
            ),
            warnings,
        )
    return SimulatedActuator(policy.simulator_latency_ms, policy.simulator_failure_rate), warnings


class ActuatorRegistry:
    """Keeps the active actuator for every compound."""

    def __init__(self) -> None:
        self._actuators: dict[uuid.UUID, BarrierActuator] = {}
        self._signatures: dict[uuid.UUID, str] = {}
        self._policies: dict[uuid.UUID, BarrierPolicy] = {}
        self._warnings: dict[uuid.UUID, list[str]] = {}
        self._lock = asyncio.Lock()

    async def for_policy(
        self, compound_id: uuid.UUID, policy: BarrierPolicy
    ) -> BarrierActuator:
        signature = _signature(policy)
        async with self._lock:
            current = self._actuators.get(compound_id)
            if current is not None and self._signatures.get(compound_id) == signature:
                return current
            if current is not None:
                try:
                    await current.aclose()
                except Exception:  # pragma: no cover - defensive
                    logger.debug("Closing replaced actuator failed", exc_info=True)
            actuator, warnings = build_actuator(policy)
            self._actuators[compound_id] = actuator
            self._signatures[compound_id] = signature
            self._policies[compound_id] = policy
            self._warnings[compound_id] = warnings
            for warning in warnings:
                logger.warning("Compound %s barrier: %s", compound_id, warning)
            logger.info(
                "Barrier driver for compound %s: %s", compound_id, actuator.driver
            )
            return actuator

    async def reset(self, compound_id: uuid.UUID | None = None) -> None:
        """Drop cached actuators (all, or a single compound)."""
        async with self._lock:
            targets = [compound_id] if compound_id else list(self._actuators)
            for key in targets:
                actuator = self._actuators.pop(key, None)
                self._signatures.pop(key, None)
                self._policies.pop(key, None)
                self._warnings.pop(key, None)
                if actuator is not None:
                    try:
                        await actuator.aclose()
                    except Exception:  # pragma: no cover - defensive
                        logger.debug("Actuator close failed", exc_info=True)

    def status(self, compound_id: uuid.UUID) -> dict[str, Any]:
        """Return driver/config/health for one compound (never raises)."""
        policy = self._policies.get(compound_id)
        actuator = self._actuators.get(compound_id)
        if policy is None or actuator is None:
            return {
                "configured": False,
                "driver": policy.driver if policy else "simulator",
                "health": {"driver": policy.driver if policy else "simulator", "ready": False},
                "warnings": list(self._warnings.get(compound_id, [])),
            }
        try:
            health = actuator.health()
        except Exception as exc:  # pragma: no cover - defensive
            health = {"driver": actuator.driver, "ready": False, "error": str(exc)}
        return {
            "configured": True,
            "driver": actuator.driver,
            "name": actuator.name,
            "config": policy.to_dict(mask_secrets=True),
            "health": health,
            "warnings": list(self._warnings.get(compound_id, [])),
        }

    def reset_sync(self) -> None:
        """Clear caches without awaiting (used by tests)."""
        self._actuators.clear()
        self._signatures.clear()
        self._policies.clear()
        self._warnings.clear()


actuator_registry = ActuatorRegistry()

__all__ = ["ActuatorRegistry", "actuator_registry", "build_actuator"]
