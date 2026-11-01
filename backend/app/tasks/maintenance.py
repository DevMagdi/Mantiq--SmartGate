"""Retention and maintenance jobs used by the scheduler and the CLI.

Design notes
------------
* **Batched deletes.** Deleting a year of detections in one statement locks a
  large part of the table (and can blow up WAL size on PostgreSQL). Rows are
  removed in batches of ``RETENTION_BATCH_SIZE`` with a hard cap of
  ``RETENTION_MAX_BATCHES`` per cycle, so a backlog is drained over several
  cycles instead of stalling the API.
* **Job isolation.** A failure in one job (e.g. a full disk while pruning
  media) never prevents the others from running; the error is logged, exposed
  on the ``maintenance.completed`` event and counted in Prometheus.
* **Different clocks per table.** Detections/snapshots follow
  ``RETENTION_DAYS`` while the access-log audit trail follows the longer
  ``RETENTION_ACCESS_LOG_DAYS``.
* **Dry run.** ``run_once(dry_run=True)`` (or ``python -m app.tasks.maintenance
  --dry-run``) reports what would be deleted without touching anything.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.events import publish_event
from app.core.logging import configure_logging, get_logger
from app.core.metrics import record_maintenance
from app.db.session import session_scope
from app.models.access import AccessLog, DetectionEvent
from app.services.maintenance import maintenance_service

logger = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Media
# --------------------------------------------------------------------------- #


def _media_cutoff(days: int, now: datetime | None) -> datetime:
    return (now or datetime.now(UTC)) - timedelta(days=days)


async def prune_media(
    retention_days: int | None = None,
    root: Path | None = None,
    *,
    now: datetime | None = None,
    dry_run: bool = False,
) -> int:
    """Delete snapshot files older than the retention window.

    Returns the number of removed (or, in dry-run mode, removable) files.
    Directories are preserved so the static media mount keeps working.
    """
    days = settings.RETENTION_DAYS if retention_days is None else retention_days
    if days <= 0:
        return 0
    cutoff_ts = _media_cutoff(days, now).timestamp()
    media_root = Path(root or settings.MEDIA_ROOT)
    if not media_root.exists():
        return 0

    removed = 0
    for path in media_root.rglob("*"):
        if not path.is_file() or path.name == ".gitkeep":
            continue
        try:
            if path.stat().st_mtime >= cutoff_ts:
                continue
            if not dry_run:
                path.unlink()
            removed += 1
        except OSError:  # pragma: no cover - best effort housekeeping
            logger.warning("Could not remove expired media file %s", path)
    if removed:
        logger.info(
            "%s %d snapshot file(s) older than %d days",
            "Would prune" if dry_run else "Pruned",
            removed,
            days,
        )
    return removed


# --------------------------------------------------------------------------- #
# Database rows
# --------------------------------------------------------------------------- #


async def _count_expired(session: AsyncSession, model: Any, cutoff: datetime) -> int:
    stmt = select(func.count(model.id)).where(model.occurred_at < cutoff)
    return int(await session.scalar(stmt) or 0)


async def _delete_batched(
    session: AsyncSession,
    model: Any,
    cutoff: datetime,
    *,
    batch_size: int,
    max_batches: int,
    dry_run: bool,
) -> tuple[int, bool]:
    """Delete expired rows in batches. Returns ``(deleted, backlog_left)``."""
    deleted = 0
    batches = 0
    while batches < max_batches:
        ids = list(
            (
                await session.execute(
                    select(model.id).where(model.occurred_at < cutoff).limit(batch_size)
                )
            )
            .scalars()
            .all()
        )
        if not ids:
            return deleted, False
        batches += 1
        if dry_run:
            deleted += len(ids)
            if len(ids) < batch_size:
                return deleted, False
            # In dry-run we cannot make progress by deleting; count one batch and stop.
            return deleted, True
        result = await session.execute(delete(model).where(model.id.in_(ids)))
        await session.commit()
        removed = int(result.rowcount or len(ids))
        deleted += removed
        if removed < batch_size:
            return deleted, False
    return deleted, True


async def purge_expired_records(
    session: AsyncSession,
    retention_days: int | None = None,
    *,
    access_log_days: int | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
    batch_size: int | None = None,
    max_batches: int | None = None,
) -> dict[str, int]:
    """Delete detection events and access logs beyond their retention windows."""
    explicit = retention_days is not None and access_log_days is None
    days = settings.RETENTION_DAYS if retention_days is None else retention_days
    log_days = (
        days
        if explicit
        else settings.RETENTION_ACCESS_LOG_DAYS
        if access_log_days is None
        else access_log_days
    )
    size = max(1, batch_size or settings.RETENTION_BATCH_SIZE)
    caps = max(1, max_batches or settings.RETENTION_MAX_BATCHES)
    stamp = now or datetime.now(UTC)
    counters = {
        "detections_purged": 0,
        "access_logs_purged": 0,
        "backlog_remaining": 0,
    }

    if days > 0:
        detections, backlog = await _delete_batched(
            session,
            DetectionEvent,
            stamp - timedelta(days=days),
            batch_size=size,
            max_batches=caps,
            dry_run=dry_run,
        )
        counters["detections_purged"] = detections
        counters["backlog_remaining"] += 1 if backlog else 0
    if log_days > 0:
        logs, backlog = await _delete_batched(
            session,
            AccessLog,
            stamp - timedelta(days=log_days),
            batch_size=size,
            max_batches=caps,
            dry_run=dry_run,
        )
        counters["access_logs_purged"] = logs
        counters["backlog_remaining"] += 1 if backlog else 0

    if counters["detections_purged"] or counters["access_logs_purged"]:
        logger.info(
            "%s %s",
            "Retention dry-run found" if dry_run else "Retention purge removed",
            {
                "detections": counters["detections_purged"],
                "access_logs": counters["access_logs_purged"],
            },
        )
    return counters


async def retention_report(
    session: AsyncSession, *, now: datetime | None = None
) -> dict[str, Any]:
    """Count rows that are already past their retention window (ops dashboard)."""
    stamp = now or datetime.now(UTC)
    detection_cutoff = stamp - timedelta(days=max(0, settings.RETENTION_DAYS))
    log_cutoff = stamp - timedelta(days=max(0, settings.RETENTION_ACCESS_LOG_DAYS))
    detections = await _count_expired(session, DetectionEvent, detection_cutoff)
    logs = await _count_expired(session, AccessLog, log_cutoff)
    return {
        "retention_days": settings.RETENTION_DAYS,
        "access_log_retention_days": settings.RETENTION_ACCESS_LOG_DAYS,
        "expired_detections": detections,
        "expired_access_logs": logs,
        "overdue": detections > 0 or logs > 0,
    }


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


async def run_once(
    retention_days: int | None = None, *, dry_run: bool = False
) -> dict[str, Any]:
    """Run every scheduled job once and return the counters.

    Jobs are isolated: a failure is recorded in ``errors`` and the rest still
    run. The result is published on the event bus and exported to Prometheus.
    """
    started = time.perf_counter()
    results: dict[str, Any] = {"dry_run": dry_run}
    errors: list[str] = []

    async def _job(name: str, coro: Any) -> Any:
        try:
            return await coro
        except Exception as exc:  # noqa: BLE001 - isolation is the point
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
            logger.exception("Maintenance job %s failed", name)
            return None

    base = await _job("permits_and_visitors", maintenance_service.run_once())
    if isinstance(base, dict):
        results.update(base)

    async with session_scope() as session:
        purged = await _job(
            "retention",
            purge_expired_records(session, retention_days, dry_run=dry_run),
        )
    if isinstance(purged, dict):
        results.update(purged)

    media = await _job("media", prune_media(retention_days, dry_run=dry_run))
    results["media_files_pruned"] = int(media or 0)

    finished_at = time.time()
    results["errors"] = errors
    results["duration_ms"] = int((time.perf_counter() - started) * 1000)
    results["ran_at"] = int(finished_at)
    results["ok"] = not errors
    record_maintenance(
        purged={
            "detections": int(results.get("detections_purged") or 0),
            "access_logs": int(results.get("access_logs_purged") or 0),
            "media_files": int(results.get("media_files_pruned") or 0),
        },
        success=not errors,
        finished_at=finished_at,
    )
    await publish_event("maintenance.completed", {k: v for k, v in results.items()})
    log = logger.info if not errors else logger.warning
    log("Maintenance cycle finished: %s", results)
    return results


async def maintenance_loop(
    interval_seconds: int | None = None,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Run maintenance forever (or until ``stop_event`` is set)."""
    interval = interval_seconds or settings.MAINTENANCE_INTERVAL_SECONDS
    stop = stop_event or asyncio.Event()
    while not stop.is_set():
        try:
            await run_once()
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            raise
        except Exception:  # pragma: no cover - keep the scheduler alive
            logger.exception("Scheduled maintenance failed")
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point used by ``python -m app.tasks`` and cron jobs."""
    parser = argparse.ArgumentParser(description="GateVision maintenance tasks")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single maintenance cycle and exit (default)",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Keep running cycles until interrupted",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=settings.MAINTENANCE_INTERVAL_SECONDS,
        help="Seconds between cycles in loop mode",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=None,
        help="Override the detection/media retention window",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be deleted without deleting anything",
    )
    args = parser.parse_args(argv)
    configure_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)

    if args.loop:
        try:
            asyncio.run(maintenance_loop(args.interval))
        except KeyboardInterrupt:  # pragma: no cover - interactive shutdown
            logger.info("Maintenance loop stopped by the operator")
        return 0

    results = asyncio.run(run_once(args.retention_days, dry_run=args.dry_run))
    print(results)
    return 0 if results.get("ok", True) else 1
