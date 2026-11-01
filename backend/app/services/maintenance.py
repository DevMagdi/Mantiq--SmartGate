"""Background maintenance: permit expiry, visitor expiry and housekeeping."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.enums import PermitStatus, VisitorStatus
from app.models.people import Permit, Visitor
from app.services.visitor_service import permit_service

logger = get_logger(__name__)


class MaintenanceService:
    """Idempotent jobs safe to run on every replica."""

    async def expire_permits(self, session: AsyncSession) -> int:
        """Move pending/active permits to their correct clock-based status."""
        changed = await permit_service.refresh_statuses(session)
        if changed:
            logger.info("Permit status refresh updated %d permit(s)", changed)
        return changed

    async def expire_visitors(self, session: AsyncSession) -> int:
        """Expire visitor invitations that are long past their window."""
        cutoff = datetime.now(UTC) - timedelta(hours=24)
        stmt = (
            select(Visitor)
            .where(
                Visitor.status.in_([VisitorStatus.PENDING, VisitorStatus.APPROVED]),
                Visitor.expected_arrival.is_not(None),
                Visitor.expected_arrival < cutoff,
            )
        )
        visitors = list((await session.execute(stmt)).scalars().all())
        changed = 0
        for visitor in visitors:
            active = await session.scalar(
                select(Permit.id).where(
                    Permit.visitor_id == visitor.id,
                    Permit.status == PermitStatus.ACTIVE,
                )
            )
            if active is None:
                visitor.status = VisitorStatus.EXPIRED
                changed += 1
        if changed:
            await session.commit()
            logger.info("Expired %d visitor invitation(s)", changed)
        return changed

    async def run_once(self) -> dict[str, int]:
        """Run every maintenance job in a single session."""
        from app.db.session import session_scope

        async with session_scope() as session:
            permits = await self.expire_permits(session)
            visitors = await self.expire_visitors(session)
        return {"permits_updated": permits, "visitors_expired": visitors}

    async def run_forever(self, interval_seconds: int = 60) -> None:
        """Loop until cancelled."""
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:  # pragma: no cover
                raise
            except Exception:  # pragma: no cover - keep the scheduler alive
                logger.exception("Maintenance cycle failed")
            await asyncio.sleep(interval_seconds)


maintenance_service = MaintenanceService()


async def start_maintenance(stop_event: asyncio.Event, interval_seconds: int = 60) -> None:
    """Run maintenance until ``stop_event`` is set."""
    while not stop_event.is_set():
        try:
            await maintenance_service.run_once()
        except Exception:  # pragma: no cover
            logger.exception("Maintenance cycle failed")
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
