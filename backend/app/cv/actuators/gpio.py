"""GPIO/relay barrier driver for Raspberry Pi (or any SBC with gpiozero).

The barrier controller usually exposes two dry-contact inputs: a pulse opens
the barrier, a second pulse closes it. ``hold`` keeps the open relay energised
for a few seconds (useful for slow sliding gates).

``simulate=true`` (default) only logs the pulse, so the driver can be enabled
on a laptop. On a Pi with the hardware attached set ``gpio.simulate=false`` and
install ``gpiozero`` (``pip install gpiozero``).
"""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any

from app.core.logging import get_logger
from app.cv.actuators.base import ActuatorResult, BarrierActuator, _Timer

logger = get_logger(__name__)


class GpioActuator(BarrierActuator):
    """Drives barrier relays through gpiozero digital outputs."""

    driver = "gpio"
    name = "gpio"

    def __init__(
        self,
        *,
        open_pin: int = 17,
        close_pin: int = 27,
        hold_pin: int | None = 22,
        active_high: bool = True,
        pulse_seconds: float = 0.6,
        backend: str = "gpiozero",
        simulate: bool = True,
    ) -> None:
        self.open_pin = open_pin
        self.close_pin = close_pin
        self.hold_pin = hold_pin
        self.active_high = active_high
        self.pulse_seconds = max(0.05, pulse_seconds)
        self.backend = backend
        self.simulate = simulate
        self._commands = 0
        self._failures = 0
        self._last_error: str | None = None

    # -------------------------------------------------------------------- pins
    def _pin_for(self, action: str) -> int | None:
        if action == "open":
            return self.open_pin
        if action == "close":
            return self.close_pin
        if action == "hold":
            return self.hold_pin if self.hold_pin is not None else self.open_pin
        return None

    def _pulse_blocking(self, pin: int, seconds: float) -> None:
        from gpiozero import DigitalOutputDevice  # lazy: needs real hardware

        device = DigitalOutputDevice(pin, active_high=self.active_high, initial_value=False)
        try:
            device.on()
            import time

            time.sleep(seconds)
        finally:
            device.off()
            device.close()

    async def send(self, action: str, gate_code: str, reason: str) -> ActuatorResult:
        timer = _Timer()
        self._commands += 1
        pin = self._pin_for(action)
        if pin is None:
            return ActuatorResult(
                accepted=False,
                driver=self.driver,
                detail=f"No GPIO pin configured for action '{action}'",
                latency_ms=timer.elapsed_ms(),
                error="pin_not_configured",
            )
        seconds = self.pulse_seconds if action != "hold" else max(self.pulse_seconds, 3.0)

        if self.simulate:
            logger.info(
                "GPIO (simulated) pin=%s pulse=%.2fs gate=%s action=%s reason=%s",
                pin,
                seconds,
                gate_code,
                action,
                reason,
            )
            await asyncio.sleep(min(seconds, 0.05))
            return ActuatorResult(
                accepted=True,
                driver=self.driver,
                detail=f"GPIO pulse simulated on pin {pin} ({action} {gate_code})",
                latency_ms=timer.elapsed_ms(),
                extra={"pin": pin, "simulated": True},
            )

        try:
            await asyncio.to_thread(self._pulse_blocking, pin, seconds)
        except ImportError:
            self._failures += 1
            self._last_error = "gpiozero is not installed"
            return ActuatorResult(
                accepted=False,
                driver=self.driver,
                detail=(
                    "GPIO driver needs gpiozero: pip install gpiozero "
                    "(or set barrier.gpio.simulate=true)"
                ),
                latency_ms=timer.elapsed_ms(),
                error="dependency_missing",
            )
        except Exception as exc:  # pragma: no cover - hardware specific
            self._failures += 1
            self._last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("GPIO pulse failed on pin %s: %s", pin, exc)
            return ActuatorResult(
                accepted=False,
                driver=self.driver,
                detail=f"GPIO pulse on pin {pin} failed: {self._last_error}",
                latency_ms=timer.elapsed_ms(),
                error=self._last_error,
            )

        logger.info(
            "GPIO pulse pin=%s %.2fs gate=%s action=%s at %s",
            pin,
            seconds,
            gate_code,
            action,
            dt.datetime.now(dt.UTC).isoformat(),
        )
        self._last_error = None
        return ActuatorResult(
            accepted=True,
            driver=self.driver,
            detail=f"GPIO pulse sent on pin {pin} ({action} {gate_code})",
            latency_ms=timer.elapsed_ms(),
            extra={"pin": pin, "pulse_seconds": seconds},
        )

    # -------------------------------------------------------------- diagnostics
    def health(self) -> dict[str, Any]:
        return {
            "driver": self.driver,
            "ready": True,
            "simulated": self.simulate,
            "backend": self.backend,
            "pins": {"open": self.open_pin, "close": self.close_pin, "hold": self.hold_pin},
            "active_high": self.active_high,
            "pulse_seconds": self.pulse_seconds,
            "commands": self._commands,
            "failures": self._failures,
            "last_error": self._last_error,
        }

    def describe(self) -> dict[str, Any]:
        return {
            "driver": self.driver,
            "name": self.name,
            "open_pin": self.open_pin,
            "close_pin": self.close_pin,
            "hold_pin": self.hold_pin,
            "pulse_seconds": self.pulse_seconds,
            "simulated": self.simulate,
        }


__all__ = ["GpioActuator"]
