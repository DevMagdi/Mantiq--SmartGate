"""Barrier actuator interface.

A *barrier actuator* is the last mile between the decision engine and the
physical gate: a webhook to a controller board, an MQTT publish to a PLC, a
GPIO pulse on a Raspberry Pi, or the built-in simulator.

Every driver returns an :class:`ActuatorResult` instead of raising, so the
access log always records what happened to the barrier and the dashboard can
show a precise failure reason.
"""

from __future__ import annotations

import abc
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

BarrierAction = Literal["open", "close", "hold"]
BARRIER_ACTIONS: tuple[BarrierAction, ...] = ("open", "close", "hold")


@dataclass(slots=True)
class ActuatorResult:
    """Outcome of a single barrier command."""

    accepted: bool
    driver: str
    detail: str
    latency_ms: int = 0
    attempts: int = 1
    external_status: int | None = None
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class BarrierActuator(abc.ABC):
    """Abstract base class for every barrier driver."""

    name: str = "actuator"
    driver: str = "simulator"

    # ---------------------------------------------------------------- commands
    async def open(self, gate_code: str, reason: str) -> ActuatorResult:
        return await self.send("open", gate_code, reason)

    async def close(self, gate_code: str, reason: str) -> ActuatorResult:
        return await self.send("close", gate_code, reason)

    async def hold(self, gate_code: str, reason: str) -> ActuatorResult:
        return await self.send("hold", gate_code, reason)

    @abc.abstractmethod
    async def send(self, action: str, gate_code: str, reason: str) -> ActuatorResult:
        """Send one command to the hardware and report the outcome."""

    # ------------------------------------------------------------- diagnostics
    def health(self) -> dict[str, Any]:
        """Return a JSON-serialisable health snapshot for the dashboard."""
        return {"driver": self.driver, "ready": True}

    def describe(self) -> dict[str, Any]:
        """Return the (secret-free) configuration of this actuator."""
        return {"driver": self.driver, "name": self.name}

    async def aclose(self) -> None:
        """Release network/hardware resources. Safe to call repeatedly."""
        return None


class _Timer:
    """Small helper to measure command latency in milliseconds."""

    def __init__(self) -> None:
        self._started = time.perf_counter()

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self._started) * 1000)


__all__ = [
    "BARRIER_ACTIONS",
    "ActuatorResult",
    "BarrierAction",
    "BarrierActuator",
    "_Timer",
]
