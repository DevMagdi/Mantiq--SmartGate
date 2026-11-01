"""Simulated barrier driver (default for demos and CI)."""

from __future__ import annotations

import asyncio
import hashlib

from app.core.logging import get_logger
from app.cv.actuators.base import ActuatorResult, BarrierActuator, _Timer

logger = get_logger(__name__)


class SimulatedActuator(BarrierActuator):
    """Pretends to drive a barrier: configurable latency and failure rate.

    A non-zero ``failure_rate`` is useful to exercise the "barrier did not
    acknowledge" paths in staging without touching real hardware.
    """

    driver = "simulator"
    name = "simulator"

    def __init__(self, latency_ms: int = 40, failure_rate: float = 0.0) -> None:
        self.latency_ms = max(0, latency_ms)
        self.failure_rate = min(max(0.0, failure_rate), 1.0)
        self._commands = 0
        self._failures = 0

    def _should_fail(self, gate_code: str, action: str) -> bool:
        if self.failure_rate <= 0:
            return False
        if self.failure_rate >= 1:
            return True
        # Deterministic per (gate, action, command index): reproducible tests.
        digest = hashlib.sha256(f"{gate_code}:{action}:{self._commands}".encode()).digest()
        roll = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
        return roll < self.failure_rate

    async def send(self, action: str, gate_code: str, reason: str) -> ActuatorResult:
        timer = _Timer()
        if self.latency_ms:
            await asyncio.sleep(self.latency_ms / 1000)
        self._commands += 1
        failed = self._should_fail(gate_code, action)
        if failed:
            self._failures += 1
            logger.warning(
                "Simulated barrier failure gate=%s action=%s reason=%s", gate_code, action, reason
            )
        else:
            logger.info(
                "Simulated barrier gate=%s action=%s reason=%s", gate_code, action, reason
            )
        return ActuatorResult(
            accepted=not failed,
            driver=self.driver,
            detail=(
                f"Simulated {action} on {gate_code}" if not failed
                else f"Simulated relay did not acknowledge {action} on {gate_code}"
            ),
            latency_ms=timer.elapsed_ms(),
            error="simulated_failure" if failed else None,
            extra={"latency_ms": self.latency_ms, "failure_rate": self.failure_rate},
        )

    def health(self) -> dict[str, object]:
        return {
            "driver": self.driver,
            "ready": True,
            "commands": self._commands,
            "failures": self._failures,
            "latency_ms": self.latency_ms,
            "failure_rate": self.failure_rate,
        }

    def describe(self) -> dict[str, object]:
        return {
            "driver": self.driver,
            "name": self.name,
            "latency_ms": self.latency_ms,
            "failure_rate": self.failure_rate,
        }


__all__ = ["SimulatedActuator"]
