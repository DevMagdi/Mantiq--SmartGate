"""Analytics and dashboard aggregation."""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.access import AccessLog, DetectionEvent
from app.models.compound import Camera, Compound, Gate
from app.models.enums import (
    AccessDecision,
    AccessDirection,
    BlacklistEntryType,
    CameraStatus,
    PermitStatus,
    VisitorStatus,
)
from app.models.people import Permit, Resident, Visitor
from app.models.security import BlacklistEntry
from app.models.vehicle import Vehicle
from app.schemas.access import AccessLogRead, DetectionEventRead
from app.schemas.analytics import (
    DashboardResponse,
    DecisionBreakdown,
    GatePerformance,
    HourlyHeatmapCell,
    MethodBreakdown,
    OccupancySnapshot,
    OverviewStats,
    PeakHourPoint,
    TrendPoint,
)

logger = get_logger(__name__)


def resolve_timezone(name: str | None) -> ZoneInfo:
    """Return a ZoneInfo, falling back to UTC for unknown identifiers."""
    try:
        return ZoneInfo(name or settings.DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("Unknown timezone %s, falling back to UTC", name)
        return ZoneInfo("UTC")


class AnalyticsService:
    """Read-only aggregations used by the dashboard and reports."""

    async def _compound_timezone(
        self, session: AsyncSession, compound_id: uuid.UUID | None
    ) -> ZoneInfo:
        if compound_id is None:
            return resolve_timezone(settings.DEFAULT_TIMEZONE)
        compound = await session.get(Compound, compound_id)
        return resolve_timezone(compound.timezone if compound else settings.DEFAULT_TIMEZONE)

    async def dashboard(
        self,
        session: AsyncSession,
        *,
        compound_id: uuid.UUID | None,
        days: int = 7,
    ) -> DashboardResponse:
        """Build the complete dashboard payload in a handful of queries."""
        days = max(1, min(days, 90))
        tz = await self._compound_timezone(session, compound_id)
        now_local = datetime.now(tz)
        today_start_local = datetime.combine(now_local.date(), time.min, tzinfo=tz)
        yesterday_start_local = today_start_local - timedelta(days=1)
        range_start_local = today_start_local - timedelta(days=days - 1)
        today_start = today_start_local.astimezone(UTC)
        yesterday_start = yesterday_start_local.astimezone(UTC)
        range_start = range_start_local.astimezone(UTC)
        now = now_local.astimezone(UTC)

        # ---------------------------------------------------------- access logs
        log_stmt = (
            select(
                AccessLog.occurred_at,
                AccessLog.decision,
                AccessLog.direction,
                AccessLog.gate_id,
                AccessLog.plate_normalized,
                AccessLog.access_method,
                AccessLog.face_similarity,
            )
            .where(AccessLog.occurred_at >= range_start)
            .where(AccessLog.occurred_at <= now)
        )
        if compound_id is not None:
            log_stmt = log_stmt.where(AccessLog.compound_id == compound_id)
        rows = (await session.execute(log_stmt)).all()

        today_rows = [row for row in rows if row[0] >= today_start]
        yesterday_rows = [
            row for row in rows if yesterday_start <= row[0] < today_start
        ]
        entries_today = sum(1 for row in today_rows if row.direction == AccessDirection.ENTRY)
        exits_today = sum(1 for row in today_rows if row.direction == AccessDirection.EXIT)
        allowed_today = sum(1 for row in today_rows if row.decision == AccessDecision.ALLOW)
        denied_today = sum(1 for row in today_rows if row.decision == AccessDecision.DENY)
        unknown_today = sum(1 for row in today_rows if row.decision == AccessDecision.UNKNOWN)
        review_today = sum(1 for row in today_rows if row.decision == AccessDecision.REVIEW)
        unique_vehicles = len({row.plate_normalized for row in today_rows if row.plate_normalized})
        yesterday_entries = sum(
            1 for row in yesterday_rows if row.direction == AccessDirection.ENTRY
        )
        entries_change = (
            round(((entries_today - yesterday_entries) / yesterday_entries) * 100, 1)
            if yesterday_entries
            else None
        )

        # ------------------------------------------------------ detection stats
        detection_stmt = select(
            DetectionEvent.occurred_at,
            DetectionEvent.plate_text,
            DetectionEvent.face_detected,
            DetectionEvent.face_matched,
            DetectionEvent.processing_ms,
        ).where(DetectionEvent.occurred_at >= today_start, DetectionEvent.occurred_at <= now)
        if compound_id is not None:
            detection_stmt = detection_stmt.where(DetectionEvent.compound_id == compound_id)
        detections = (await session.execute(detection_stmt)).all()
        detection_total = len(detections)
        plate_reads = sum(1 for row in detections if row.plate_text)
        faces_detected = sum(1 for row in detections if row.face_detected)
        faces_matched = sum(1 for row in detections if row.face_matched)
        processing = [row.processing_ms for row in detections if row.processing_ms is not None]

        # ------------------------------------------------------------- counters
        def scope(stmt, column=Compound.id):  # type: ignore[no-untyped-def]
            return stmt.where(column == compound_id) if compound_id is not None else stmt

        vehicles_inside = await session.scalar(
            scope(select(func.count(Vehicle.id)).where(Vehicle.is_inside.is_(True)), Vehicle.compound_id)
        )
        active_visitors = await session.scalar(
            scope(
                select(func.count(Visitor.id)).where(
                    Visitor.status == VisitorStatus.CHECKED_IN
                ),
                Visitor.compound_id,
            )
        )
        active_permits = await session.scalar(
            scope(
                select(func.count(Permit.id)).where(
                    Permit.status == PermitStatus.ACTIVE,
                    Permit.start_at <= now,
                    Permit.end_at >= now,
                    Permit.entries_used < Permit.max_entries,
                ),
                Permit.compound_id,
            )
        )
        residents_total = await session.scalar(
            scope(select(func.count(Resident.id)), Resident.compound_id)
        )
        vehicles_total = await session.scalar(
            scope(select(func.count(Vehicle.id)), Vehicle.compound_id)
        )
        blacklist_active = await session.scalar(
            scope(
                select(func.count(BlacklistEntry.id)).where(
                    BlacklistEntry.is_active.is_(True),
                    (BlacklistEntry.expires_at.is_(None)) | (BlacklistEntry.expires_at > now),
                ),
                BlacklistEntry.compound_id,
            )
        )
        camera_stmt = select(Camera.status)
        if compound_id is not None:
            camera_stmt = camera_stmt.join(Gate, Camera.gate_id == Gate.id).where(
                Gate.compound_id == compound_id
            )
        camera_rows = (await session.execute(camera_stmt)).scalars().all()
        cameras_total = len(camera_rows)
        cameras_online = sum(1 for status in camera_rows if status == CameraStatus.ONLINE)

        overview = OverviewStats(
            entries_today=entries_today,
            exits_today=exits_today,
            allowed_today=allowed_today,
            denied_today=denied_today,
            unknown_today=unknown_today,
            review_today=review_today,
            face_match_rate=round(faces_matched / faces_detected, 4) if faces_detected else 0.0,
            plate_read_rate=round(plate_reads / detection_total, 4) if detection_total else 0.0,
            unique_vehicles_today=unique_vehicles,
            vehicles_inside=int(vehicles_inside or 0),
            active_visitors=int(active_visitors or 0),
            active_permits=int(active_permits or 0),
            residents_total=int(residents_total or 0),
            vehicles_total=int(vehicles_total or 0),
            blacklist_active=int(blacklist_active or 0),
            cameras_online=cameras_online,
            cameras_total=cameras_total,
            avg_processing_ms=round(sum(processing) / len(processing), 1) if processing else None,
            entries_change_pct=entries_change,
        )

        # -------------------------------------------------------- time buckets
        hour_entries: Counter[int] = Counter()
        hour_exits: Counter[int] = Counter()
        trend: dict[date, dict[str, int]] = {}
        heat: Counter[tuple[int, int]] = Counter()
        for row in rows:
            local_dt = row.occurred_at.astimezone(tz)
            if row.direction == AccessDirection.ENTRY:
                hour_entries[local_dt.hour] += 1
            else:
                hour_exits[local_dt.hour] += 1
            heat[(local_dt.weekday(), local_dt.hour)] += 1
            bucket = trend.setdefault(
                local_dt.date(),
                {"allowed": 0, "denied": 0, "unknown": 0, "review": 0, "total": 0},
            )
            bucket[row.decision.value] = bucket.get(row.decision.value, 0) + 1
            bucket["total"] += 1

        peak_hours = [
            PeakHourPoint(
                hour=hour,
                label=f"{hour:02d}:00",
                entries=hour_entries.get(hour, 0),
                exits=hour_exits.get(hour, 0),
                total=hour_entries.get(hour, 0) + hour_exits.get(hour, 0),
            )
            for hour in range(24)
        ]
        trend_points: list[TrendPoint] = []
        for offset in range(days):
            day = (range_start_local + timedelta(days=offset)).date()
            bucket = trend.get(day, {})
            trend_points.append(
                TrendPoint(
                    day=day,
                    allowed=int(bucket.get("allowed", 0)),
                    denied=int(bucket.get("denied", 0)),
                    unknown=int(bucket.get("unknown", 0)),
                    review=int(bucket.get("review", 0)),
                    total=int(bucket.get("total", 0)),
                )
            )
        heatmap = [
            HourlyHeatmapCell(day_of_week=day, hour=hour, count=count)
            for (day, hour), count in sorted(heat.items())
        ]

        # ----------------------------------------------------------- breakdowns
        decision_counter = Counter(row.decision.value for row in rows)
        total_decisions = sum(decision_counter.values()) or 1
        decision_breakdown = [
            DecisionBreakdown(
                decision=AccessDecision(value),
                count=count,
                percentage=round(count / total_decisions * 100, 1),
            )
            for value, count in decision_counter.most_common()
        ]
        method_counter = Counter(row.access_method.value for row in rows)
        method_breakdown = [
            MethodBreakdown(method=method, count=count) for method, count in method_counter.most_common()
        ]

        # ------------------------------------------------------- gate performance
        gate_stmt = select(Gate)
        if compound_id is not None:
            gate_stmt = gate_stmt.where(Gate.compound_id == compound_id)
        gates = list((await session.execute(gate_stmt)).scalars().all())
        gate_stats: dict[uuid.UUID, dict[str, object]] = defaultdict(
            lambda: {"total": 0, "allowed": 0, "denied": 0, "unknown": 0, "review": 0, "last": None}
        )
        for row in rows:
            stats = gate_stats[row.gate_id]
            stats["total"] = int(stats["total"]) + 1  # type: ignore[arg-type]
            if row.decision == AccessDecision.ALLOW:
                stats["allowed"] = int(stats["allowed"]) + 1  # type: ignore[arg-type]
            elif row.decision == AccessDecision.DENY:
                stats["denied"] = int(stats["denied"]) + 1  # type: ignore[arg-type]
            elif row.decision == AccessDecision.UNKNOWN:
                stats["unknown"] = int(stats["unknown"]) + 1  # type: ignore[arg-type]
            else:
                stats["review"] = int(stats["review"]) + 1  # type: ignore[arg-type]
            if stats["last"] is None or row.occurred_at > stats["last"]:  # type: ignore[operator]
                stats["last"] = row.occurred_at
        gate_performance = [
            GatePerformance(
                gate_id=gate.id,
                gate_name=gate.name,
                gate_code=gate.code,
                direction=gate.direction,
                total=int(gate_stats[gate.id]["total"]),
                allowed=int(gate_stats[gate.id]["allowed"]),
                denied=int(gate_stats[gate.id]["denied"]),
                unknown=int(gate_stats[gate.id]["unknown"]),
                review=int(gate_stats[gate.id]["review"]),
                last_activity_at=gate_stats[gate.id]["last"],  # type: ignore[arg-type]
            )
            for gate in gates
        ]

        # --------------------------------------------------------------- recent
        recent_stmt = select(AccessLog)
        if compound_id is not None:
            recent_stmt = recent_stmt.where(AccessLog.compound_id == compound_id)
        recent_stmt = recent_stmt.order_by(AccessLog.occurred_at.desc()).limit(8)
        recent_access = list((await session.execute(recent_stmt)).scalars().unique().all())

        detection_recent_stmt = select(DetectionEvent)
        if compound_id is not None:
            detection_recent_stmt = detection_recent_stmt.where(
                DetectionEvent.compound_id == compound_id
            )
        detection_recent_stmt = detection_recent_stmt.order_by(
            DetectionEvent.occurred_at.desc()
        ).limit(8)
        recent_detections = list(
            (await session.execute(detection_recent_stmt)).scalars().unique().all()
        )

        return DashboardResponse(
            generated_at=datetime.now(UTC),
            range_start=range_start,
            range_end=now,
            overview=overview,
            peak_hours=peak_hours,
            trend=trend_points,
            decision_breakdown=decision_breakdown,
            method_breakdown=method_breakdown,
            gate_performance=gate_performance,
            heatmap=heatmap,
            recent_access=[AccessLogRead.model_validate(item) for item in recent_access],
            recent_detections=[DetectionEventRead.model_validate(item) for item in recent_detections],
        )

    async def trend(
        self,
        session: AsyncSession,
        *,
        compound_id: uuid.UUID | None,
        days: int = 7,
        direction: AccessDirection | None = None,
    ) -> list[TrendPoint]:
        dashboard = await self.dashboard(session, compound_id=compound_id, days=days)
        if direction is None:
            return dashboard.trend
        tz = await self._compound_timezone(session, compound_id)
        now = datetime.now(tz)
        start = datetime.combine(now.date() - timedelta(days=days - 1), time.min, tzinfo=tz).astimezone(UTC)
        stmt = select(AccessLog.occurred_at, AccessLog.decision).where(
            AccessLog.occurred_at >= start, AccessLog.direction == direction
        )
        if compound_id is not None:
            stmt = stmt.where(AccessLog.compound_id == compound_id)
        rows = (await session.execute(stmt)).all()
        buckets: dict[date, TrendPoint] = {
            (now.date() - timedelta(days=days - 1 - offset)): TrendPoint(
                day=now.date() - timedelta(days=days - 1 - offset)
            )
            for offset in range(days)
        }
        for occurred_at, decision in rows:
            day = occurred_at.astimezone(tz).date()
            point = buckets.get(day)
            if point is None:
                continue
            field_by_decision = {
                AccessDecision.ALLOW: "allowed",
                AccessDecision.DENY: "denied",
                AccessDecision.UNKNOWN: "unknown",
                AccessDecision.REVIEW: "review",
            }
            field = field_by_decision[decision]
            setattr(point, field, getattr(point, field) + 1)
            point.total += 1
        return list(buckets.values())

    async def occupancy(
        self, session: AsyncSession, *, compound_id: uuid.UUID | None
    ) -> OccupancySnapshot:
        dashboard = await self.dashboard(session, compound_id=compound_id, days=1)
        return OccupancySnapshot(
            inside_now=dashboard.overview.vehicles_inside,
            entries_today=dashboard.overview.entries_today,
            exits_today=dashboard.overview.exits_today,
            net_change=dashboard.overview.entries_today - dashboard.overview.exits_today,
            by_gate=dashboard.gate_performance,
        )

    async def blacklist_breakdown(
        self, session: AsyncSession, *, compound_id: uuid.UUID | None
    ) -> dict[str, int]:
        stmt = select(BlacklistEntry.entry_type, func.count(BlacklistEntry.id)).where(
            BlacklistEntry.is_active.is_(True)
        )
        if compound_id is not None:
            stmt = stmt.where(BlacklistEntry.compound_id == compound_id)
        stmt = stmt.group_by(BlacklistEntry.entry_type)
        rows = (await session.execute(stmt)).all()
        counts = {entry_type.value: 0 for entry_type in BlacklistEntryType}
        for entry_type, count in rows:
            counts[entry_type.value] = int(count)
        return counts


analytics_service = AnalyticsService()
