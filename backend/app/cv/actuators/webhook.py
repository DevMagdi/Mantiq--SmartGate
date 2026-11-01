"""HTTP webhook barrier driver.

Many barrier controller boards (and every "smart relay" vendor) expose a small
HTTP API. This driver posts a signed JSON command so the controller can verify
that the request really came from GateVision:

```
POST https://controller.local/api/barrier
X-GateVision-Timestamp: 1767225600
X-GateVision-Signature: sha256=a1b2c3...
Content-Type: application/json

{"event_id": "...", "gate": "GATE-IN", "action": "open", "reason": "...",
 "issued_at": "2026-11-01T10:00:00+00:00", "source": "gatevision"}
```

The signature is ``HMAC-SHA256(secret, f"{timestamp}.{body}")`` — copy the
snippet from ``docs/hardware.md`` into the controller firmware/script to verify
it. Requests are retried on transport errors, ``429`` and ``5xx`` responses with
exponential backoff.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import hmac
import json
import uuid
from typing import Any

import httpx

from app.core.logging import get_logger
from app.cv.actuators.base import ActuatorResult, BarrierActuator, _Timer

logger = get_logger(__name__)

SIGNATURE_HEADER = "X-GateVision-Signature"
TIMESTAMP_HEADER = "X-GateVision-Timestamp"
EVENT_HEADER = "X-GateVision-Event-Id"


def sign_payload(secret: str, timestamp: str, body: bytes) -> str:
    """Return the ``sha256=...`` signature for a webhook body."""
    digest = hmac.new(
        secret.encode("utf-8"), f"{timestamp}.".encode("utf-8") + body, hashlib.sha256
    ).hexdigest()
    return f"sha256={digest}"


class WebhookActuator(BarrierActuator):
    """Posts signed barrier commands to a controller webhook."""

    driver = "webhook"
    name = "webhook"

    def __init__(
        self,
        url: str,
        *,
        secret: str | None = None,
        timeout: float = 3.0,
        retries: int = 2,
        verify_tls: bool = True,
        retry_backoff: float = 0.25,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.url = url
        self.secret = secret
        self.timeout = timeout
        self.retries = retries
        self.verify_tls = verify_tls
        self.retry_backoff = max(0.0, retry_backoff)
        self.transport = transport
        self._last_status: int | None = None
        self._last_error: str | None = None
        self._consecutive_failures = 0
        self._commands = 0

    # ------------------------------------------------------------------ payload
    def _payload(self, action: str, gate_code: str, reason: str) -> tuple[dict[str, Any], bytes, str]:
        issued_at = dt.datetime.now(dt.UTC)
        payload: dict[str, Any] = {
            "event_id": str(uuid.uuid4()),
            "gate": gate_code,
            "action": action,
            "reason": reason,
            "issued_at": issued_at.isoformat(),
            "source": "gatevision",
        }
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        timestamp = str(int(issued_at.timestamp()))
        return payload, body, timestamp

    def _headers(self, payload: dict[str, Any], body: bytes, timestamp: str) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "GateVision-Barrier/1.0",
            TIMESTAMP_HEADER: timestamp,
            EVENT_HEADER: str(payload["event_id"]),
            "X-GateVision-Action": str(payload["action"]),
        }
        if self.secret:
            headers[SIGNATURE_HEADER] = sign_payload(self.secret, timestamp, body)
        return headers

    # --------------------------------------------------------------------- send
    async def send(self, action: str, gate_code: str, reason: str) -> ActuatorResult:
        timer = _Timer()
        payload, body, timestamp = self._payload(action, gate_code, reason)
        headers = self._headers(payload, body, timestamp)
        self._commands += 1
        attempts = 0
        last_error: str | None = None
        last_status: int | None = None
        delay = self.retry_backoff
        while attempts <= self.retries:
            attempts += 1
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout, verify=self.verify_tls, transport=self.transport
                ) as client:
                    response = await client.post(self.url, content=body, headers=headers)
                last_status = response.status_code
                self._last_status = last_status
                if response.status_code < 400:
                    self._consecutive_failures = 0
                    self._last_error = None
                    return ActuatorResult(
                        accepted=True,
                        driver=self.driver,
                        detail=(
                            f"Webhook accepted {action} on {gate_code} "
                            f"(HTTP {last_status}, {attempts} attempt(s))"
                        ),
                        latency_ms=timer.elapsed_ms(),
                        attempts=attempts,
                        external_status=last_status,
                    )
                snippet = (response.text or "").strip().replace("\n", " ")[:160]
                last_error = f"HTTP {last_status}: {snippet}" if snippet else f"HTTP {last_status}"
                retryable = last_status >= 500 or last_status == 429
                logger.warning(
                    "Gate webhook rejected %s for %s (HTTP %s, attempt %s/%s)",
                    action,
                    gate_code,
                    last_status,
                    attempts,
                    self.retries + 1,
                )
                if not retryable:
                    break
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                self._last_error = last_error
                logger.warning(
                    "Gate webhook error for %s (attempt %s/%s): %s",
                    gate_code,
                    attempts,
                    self.retries + 1,
                    exc,
                )
            if attempts <= self.retries and delay:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 4.0)

        self._consecutive_failures += 1
        self._last_error = last_error
        return ActuatorResult(
            accepted=False,
            driver=self.driver,
            detail=f"Webhook failed to {action} {gate_code}: {last_error or 'unknown error'}",
            latency_ms=timer.elapsed_ms(),
            attempts=attempts,
            external_status=last_status,
            error=last_error or "webhook_failed",
        )

    # -------------------------------------------------------------- diagnostics
    def health(self) -> dict[str, Any]:
        return {
            "driver": self.driver,
            "ready": bool(self.url),
            "url": self.url,
            "signed": bool(self.secret),
            "verify_tls": self.verify_tls,
            "retries": self.retries,
            "timeout_seconds": self.timeout,
            "commands": self._commands,
            "consecutive_failures": self._consecutive_failures,
            "last_status_code": self._last_status,
            "last_error": self._last_error,
        }

    def describe(self) -> dict[str, Any]:
        return {
            "driver": self.driver,
            "name": self.name,
            "url": self.url,
            "signed": bool(self.secret),
            "timeout_seconds": self.timeout,
            "retries": self.retries,
            "verify_tls": self.verify_tls,
        }


__all__ = ["SIGNATURE_HEADER", "TIMESTAMP_HEADER", "EVENT_HEADER", "WebhookActuator", "sign_payload"]
