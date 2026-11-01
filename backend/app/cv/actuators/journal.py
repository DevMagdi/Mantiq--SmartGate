"""In-memory journal of barrier commands.

Barrier commands are the highest-risk action in the system, so every attempt is
recorded with its driver, latency and outcome. The journal is intentionally an
in-process ring buffer (last 500 commands): it gives the dashboard a cheap live
view, while the durable audit trail stays in ``access_logs``/application logs.
"""

from __future__ import annotations

import datetime as dt
import threading
import uuid
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from typing import Any

from app.cv.actuators.base import ActuatorResult

MAX_RECORDS = 500


@dataclass(slots=True)
class CommandRecord:
    """One barrier command attempt."""

    id: str
    occurred_at: str
    gate_code: str
    gate_id: str | None
    compound_id: str | None
    action: str
    driver: str
    accepted: bool
    latency_ms: int
    attempts: int
    detail: str
    actor: str
    reason: str
    error: str | None = None
    external_status: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class CommandJournal:
    """Thread-safe ring buffer with simple counters."""

    def __init__(self, max_records: int = MAX_RECORDS) -> None:
        self._records: deque[CommandRecord] = deque(maxlen=max_records)
        self._lock = threading.Lock()
        self._counters: Counter[str] = Counter()
        self._by_driver: Counter[str] = Counter()
        self._by_action: Counter[str] = Counter()

    def record(
        self,
        *,
        gate_code: str,
        action: str,
        result: ActuatorResult,
        actor: str,
        reason: str,
        gate_id: uuid.UUID | str | None = None,
        compound_id: uuid.UUID | str | None = None,
    ) -> CommandRecord:
        record = CommandRecord(
            id=str(uuid.uuid4()),
            occurred_at=dt.datetime.now(dt.UTC).isoformat(),
            gate_code=gate_code,
            gate_id=str(gate_id) if gate_id else None,
            compound_id=str(compound_id) if compound_id else None,
            action=action,
            driver=result.driver,
            accepted=result.accepted,
            latency_ms=result.latency_ms,
            attempts=result.attempts,
            detail=result.detail,
            actor=actor,
            reason=reason,
            error=result.error,
            external_status=result.external_status,
            extra=dict(result.extra or {}),
        )
        with self._lock:
            self._records.append(record)
            self._counters["total"] += 1
            self._counters["accepted" if result.accepted else "failed"] += 1
            self._by_driver[result.driver] += 1
            self._by_action[action] += 1
        return record

    def recent(
        self,
        limit: int = 20,
        *,
        compound_id: str | None = None,
        gate_code: str | None = None,
    ) -> list[CommandRecord]:
        with self._lock:
            records = list(self._records)
        if compound_id is not None:
            records = [item for item in records if item.compound_id == str(compound_id)]
        if gate_code is not None:
            records = [item for item in records if item.gate_code == gate_code]
        return list(reversed(records))[: max(1, min(limit, MAX_RECORDS))]

    def summary(self) -> dict[str, Any]:
        with self._lock:
            last = self._records[-1] if self._records else None
            counters = dict(self._counters)
            by_driver = dict(self._by_driver)
            by_action = dict(self._by_action)
        total = counters.get("total", 0)
        accepted = counters.get("accepted", 0)
        return {
            "total": total,
            "accepted": accepted,
            "failed": counters.get("failed", 0),
            "success_rate": round(accepted / total, 3) if total else None,
            "by_driver": by_driver,
            "by_action": by_action,
            "last_command": last.as_dict() if last else None,
        }

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._counters.clear()
            self._by_driver.clear()
            self._by_action.clear()


command_journal = CommandJournal()

__all__ = ["CommandJournal", "CommandRecord", "MAX_RECORDS", "command_journal"]
