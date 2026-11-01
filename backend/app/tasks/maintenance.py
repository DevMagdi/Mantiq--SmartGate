"""Retention and maintenance jobs used by the scheduler and the CLI."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.events import publish_event
from app.core.logging import configure_logging, get_logger
from app.db.session import session_scope
from app.models.access import AccessLog, DetectionEvent
from app.services.maintenance import maintenance_service

logger = get_logger(__name__)


async def prune_media(
    retention_days: int | None = None,
    root: Path | None = None,
    *,
    now: datetime | None = None,
) -> int:
    """Delete snapshot files older than the retention window.

    Returns the number of removed files. Directories are preserved so the
    static media mount keeps working after a cleanup.
    """
    days = settings.RETENTION_DAYS if retention_days is None else retention_days
    if days <= 0:
        return 0
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    cutoff_ts = cutoff.timestamp()
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
            path.unlink()
            removed += 1
        except OSError:  # pragma: no cover - best effort housekeeping
            logger.warning("Could not remove expired media file %s", path)
    if removed:
        logger.info("Pruned %d snapshot file(s) older than %d days", removed, days)
    return removed


async def purge_expired_records(
    session: AsyncSession,
    retention_days: int | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """Delete detection events and access logs beyond the retention window."""
    days = settings.RETENTION_DAYS if retention_days is None else retention_days
    if days <= 0:
        return {"detections_purged": 0, "access_logs_purged": 0}
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)

    detections = await session.execute(
        delete(DetectionEvent).where(DetectionEvent.occurred_at < cutoff)
    )
    logs = await session.execute(delete(AccessLog).where(AccessLog.occurred_at < cutoff))
    await session.commit()
    purged = {
        "detections_purged": int(detections.rowcount or 0),
        "access_logs_purged": int(logs.rowcount or 0),
    }
    if purged["detections_purged"] or purged["access_logs_purged"]:
        logger.info("Retention purge removed %s", purged)
    return purged


async def run_once(retention_days: int | None = None) -> dict[str, int]:
    """Run every scheduled job once and return the counters."""
    results = await maintenance_service.run_once()
    async with session_scope() as session:
        results.update(await purge_expired_records(session, retention_days))
    results["media_files_pruned"] = await prune_media(retention_days)
    results["ran_at"] = int(time.time())
    await publish_event("maintenance.completed", dict(results))
    logger.info("Maintenance cycle finished: %s", results)
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
        default=settings.RETENTION_DAYS,
        help="Delete detections/logs/snapshots older than this many days",
    )
    args = parser.parse_args(argv)
    configure_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)

    if args.loop:
        try:
            asyncio.run(maintenance_loop(args.interval))
        except KeyboardInterrupt:  # pragma: no cover - interactive shutdown
            logger.info("Maintenance loop stopped by the operator")
        return 0

    results = asyncio.run(run_once(args.retention_days))
    print(results)
    return 0
