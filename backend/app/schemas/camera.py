"""Schemas for camera health, stream probes and real-mode diagnostics."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class CameraHealthItem(BaseModel):
    """Health of one camera as seen by the dashboard."""

    camera_id: uuid.UUID
    name: str
    gate_id: uuid.UUID
    gate_name: str
    gate_code: str
    source_type: str
    source: str = Field(description="Stream URL with credentials masked")
    is_active: bool
    status: str
    stale: bool = Field(description="True when no frame arrived for longer than the threshold")
    resolution: str | None = None
    fps_limit: float
    last_frame_at: str | None = None
    frame_age_seconds: float | None = None
    last_error: str | None = None
    worker_alive: bool | None = None
    observed_fps: float | None = None


class CameraHealthCounts(BaseModel):
    total: int = 0
    online: int = 0
    offline: int = 0
    error: int = 0
    disabled: int = 0
    stale: int = 0
    demo: int = 0


class CameraHealthResponse(BaseModel):
    """Fleet health for one compound (counters + per-camera detail)."""

    compound_id: uuid.UUID
    generated_at: str
    stale_after_seconds: int
    counts: CameraHealthCounts
    total: int = 0
    online: int = 0
    offline: int = 0
    error: int = 0
    disabled: int = 0
    stale: int = 0
    demo: int = 0
    cameras: list[CameraHealthItem] = Field(default_factory=list)


class CameraProbeResponse(BaseModel):
    """Result of a one-shot stream test ("Test stream" button)."""

    ok: bool
    camera_id: uuid.UUID
    camera_name: str
    source: str
    source_type: str
    frames: int
    latency_ms: int
    open_ms: int
    width: int | None = None
    height: int | None = None
    brightness: float | None = None
    preview_url: str | None = None
    error: str | None = None
    hint: str | None = Field(
        default=None, description="Actionable next step when the probe failed"
    )


class RealModeStatus(BaseModel):
    """Everything ops needs to confirm the system really is running live."""

    mode: str
    real_detections_only: bool
    engine_ready: bool
    warnings: list[str] = Field(default_factory=list)
    cameras_total: int = 0
    cameras_online: int = 0
    demo_cameras: int = 0
    barrier_driver: str = ""
    models: dict[str, str] = Field(default_factory=dict)


__all__ = [
    "CameraHealthCounts",
    "CameraHealthItem",
    "CameraHealthResponse",
    "CameraProbeResponse",
    "RealModeStatus",
]
