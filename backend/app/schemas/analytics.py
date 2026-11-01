"""Analytics and dashboard schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.enums import AccessDecision, AccessDirection, GateDirection
from app.schemas.access import AccessLogRead, DetectionEventRead


class OverviewStats(BaseModel):
    """Headline KPIs displayed on the dashboard."""

    entries_today: int = 0
    exits_today: int = 0
    allowed_today: int = 0
    denied_today: int = 0
    unknown_today: int = 0
    review_today: int = 0
    face_match_rate: float = Field(default=0.0, ge=0, le=1)
    plate_read_rate: float = Field(default=0.0, ge=0, le=1)
    unique_vehicles_today: int = 0
    vehicles_inside: int = 0
    active_visitors: int = 0
    active_permits: int = 0
    residents_total: int = 0
    vehicles_total: int = 0
    blacklist_active: int = 0
    cameras_online: int = 0
    cameras_total: int = 0
    avg_processing_ms: float | None = None
    entries_change_pct: float | None = Field(
        default=None, description="Percentage change in entries versus the previous day"
    )


class PeakHourPoint(BaseModel):
    hour: int = Field(ge=0, le=23)
    label: str
    entries: int = 0
    exits: int = 0
    total: int = 0


class TrendPoint(BaseModel):
    day: date
    allowed: int = 0
    denied: int = 0
    unknown: int = 0
    review: int = 0
    total: int = 0


class DecisionBreakdown(BaseModel):
    decision: AccessDecision
    count: int
    percentage: float


class MethodBreakdown(BaseModel):
    method: str
    count: int


class GatePerformance(BaseModel):
    gate_id: uuid.UUID
    gate_name: str
    gate_code: str
    direction: GateDirection
    total: int = 0
    allowed: int = 0
    denied: int = 0
    unknown: int = 0
    review: int = 0
    last_activity_at: datetime | None = None


class HourlyHeatmapCell(BaseModel):
    day_of_week: int = Field(ge=0, le=6)
    hour: int = Field(ge=0, le=23)
    count: int = 0


class ResidentVehicleStats(BaseModel):
    total_residents: int = 0
    active_residents: int = 0
    total_units: int = 0
    occupied_units: int = 0
    total_vehicles: int = 0
    active_vehicles: int = 0
    visitors_today: int = 0
    permits_today: int = 0


class ReasonBreakdown(BaseModel):
    """How often a decision reason was used (top reasons are actionable)."""

    reason_code: str
    decision: str
    count: int
    percentage: float


class DashboardResponse(BaseModel):
    """Everything the dashboard needs in a single round-trip."""

    generated_at: datetime
    range_start: datetime
    range_end: datetime
    overview: OverviewStats
    peak_hours: list[PeakHourPoint]
    trend: list[TrendPoint]
    decision_breakdown: list[DecisionBreakdown]
    method_breakdown: list[MethodBreakdown]
    gate_performance: list[GatePerformance]
    reason_breakdown: list[ReasonBreakdown] = Field(default_factory=list)
    barrier_failures: int = 0
    heatmap: list[HourlyHeatmapCell] = Field(default_factory=list)
    recent_access: list[AccessLogRead] = Field(default_factory=list)
    recent_detections: list[DetectionEventRead] = Field(default_factory=list)


class AccessTrendResponse(BaseModel):
    direction: AccessDirection | None = None
    points: list[TrendPoint]


class OccupancySnapshot(BaseModel):
    inside_now: int
    entries_today: int
    exits_today: int
    net_change: int
    by_gate: list[GatePerformance]
