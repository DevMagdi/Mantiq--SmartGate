"""Camera operations: stream probing, health reporting and env bootstrap.

Everything the admin dashboard needs to bring a real compound online lives here:

* :meth:`CameraService.probe` opens a camera *once*, grabs a few frames and
  returns latency, resolution, brightness and a preview JPEG URL — this is what
  the "Test stream" button in Settings → Cameras calls.
* :meth:`CameraService.health` merges the database row (last frame, last error)
  with the live worker state from the in-process camera manager, so the Live
  Monitor can show ``online / stale / offline`` per camera.
* :meth:`CameraService.ensure_from_env` creates camera records from
  ``CAMERAS_JSON`` so a fresh box can be wired up without clicking through the
  UI (useful for `docker compose up` on a client site).
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.logging import get_logger
from app.cv.manager import get_camera_manager
from app.cv.snapshots import SnapshotStore
from app.cv.sources import OpenCVFrameSource, redact_source
from app.cv.utils import mean_brightness
from app.models.compound import Camera, Gate
from app.models.enums import CameraSourceType, CameraStatus

logger = get_logger(__name__)

# A camera that has not produced a frame for this long is reported as stale even
# if the row still says "online" (worker crashed, host rebooted, …).
STALE_AFTER_SECONDS = 60


@dataclass(slots=True)
class ProbeResult:
    """Outcome of a one-shot stream test."""

    ok: bool
    camera_id: uuid.UUID
    camera_name: str
    source: str
    source_type: str
    frames: int
    latency_ms: int
    open_ms: int
    width: int | None
    height: int | None
    brightness: float | None
    preview_url: str | None
    error: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "camera_id": str(self.camera_id),
            "camera_name": self.camera_name,
            "source": self.source,
            "source_type": self.source_type,
            "frames": self.frames,
            "latency_ms": self.latency_ms,
            "open_ms": self.open_ms,
            "width": self.width,
            "height": self.height,
            "brightness": round(self.brightness, 1) if self.brightness is not None else None,
            "preview_url": self.preview_url,
            "error": self.error,
        }


class CameraService:
    """Stream probes and health aggregation for the camera fleet."""

    def __init__(self, store: SnapshotStore | None = None) -> None:
        self.store = store or SnapshotStore()

    # ------------------------------------------------------------------ reading
    async def get(self, session: AsyncSession, camera_id: uuid.UUID) -> Camera:
        camera = await session.get(Camera, camera_id)
        if camera is None:
            raise NotFoundError("Camera not found", code="camera_not_found")
        return camera

    # -------------------------------------------------------------------- probe
    def _probe_sync(self, camera_id: uuid.UUID, name: str, source_type: str, url: str) -> ProbeResult:
        """Open the stream, read a few frames, and persist one preview image."""
        started = time.perf_counter()
        opened = time.perf_counter()
        source = OpenCVFrameSource(url, name=name)
        result = ProbeResult(
            ok=False,
            camera_id=camera_id,
            camera_name=name,
            source=redact_source(url),
            source_type=source_type,
            frames=0,
            latency_ms=0,
            open_ms=0,
            width=None,
            height=None,
            brightness=None,
            preview_url=None,
            error=None,
        )
        try:
            source.open()
        except Exception as exc:  # noqa: BLE001 - driver errors are user facing
            result.open_ms = int((time.perf_counter() - opened) * 1000)
            result.latency_ms = int((time.perf_counter() - started) * 1000)
            result.error = str(exc)
            source.close()
            return result

        result.open_ms = int((time.perf_counter() - opened) * 1000)
        frames = max(1, min(settings.CV_CAMERA_PROBE_FRAMES, 30))
        first_frame = None
        try:
            for _ in range(frames):
                image = source.read()
                if image is None:
                    break
                result.frames += 1
                if first_frame is None:
                    first_frame = image
            if first_frame is not None:
                height, width = first_frame.shape[:2]
                result.width = int(width)
                result.height = int(height)
                result.brightness = mean_brightness(first_frame)
                try:
                    result.preview_url = self.store.save_image(first_frame, kind="probes")
                except Exception as exc:  # pragma: no cover - disk problems
                    logger.warning("Could not store camera probe preview: %s", exc)
        finally:
            source.close()

        result.latency_ms = int((time.perf_counter() - started) * 1000)
        result.ok = result.frames > 0
        if not result.ok and not result.error:
            result.error = "Camera opened but no frame could be decoded"
        if settings.CV_LOW_LIGHT_ENHANCE and result.brightness is not None:
            if result.brightness < settings.CV_LOW_LIGHT_THRESHOLD:
                logger.info(
                    "Camera %s looks dark (brightness %.1f); low-light enhancement will be applied",
                    name,
                    result.brightness,
                )
        return result

    async def probe(self, session: AsyncSession, camera: Camera) -> ProbeResult:
        """Test a camera stream and record the outcome on the camera row."""
        import asyncio

        if (camera.source_type or "").lower() == str(CameraSourceType.DEMO):
            raise BadRequestError(
                "Demo cameras cannot be probed. Configure a real RTSP/USB source instead."
            )
        result = await asyncio.to_thread(
            self._probe_sync,
            camera.id,
            camera.name,
            str(camera.source_type),
            camera.source_url,
        )
        now = datetime.now(UTC)
        if result.ok:
            camera.status = CameraStatus.ONLINE
            camera.last_frame_at = now
            camera.last_error = None
            if result.width and result.height:
                camera.resolution = f"{result.width}x{result.height}"
        else:
            camera.status = CameraStatus.ERROR
            camera.last_error = (result.error or "Stream test failed")[:2000]
        await session.commit()
        await session.refresh(camera)
        logger.info(
            "Camera probe %s: ok=%s frames=%s latency=%sms error=%s",
            camera.name,
            result.ok,
            result.frames,
            result.latency_ms,
            result.error,
        )
        return result

    # ------------------------------------------------------------------- health
    def _worker_state(self) -> dict[str, dict[str, Any]]:
        manager = get_camera_manager()
        if manager is None:
            return {}
        try:
            workers = manager.status().get("workers", [])
        except Exception:  # pragma: no cover - defensive
            return {}
        return {str(item["camera_id"]): dict(item) for item in workers}  # type: ignore[arg-type]

    def _worker_for(self, workers: dict[str, dict[str, Any]], camera_id: uuid.UUID) -> dict[str, Any] | None:
        return workers.get(str(camera_id))

    async def health(
        self, session: AsyncSession, compound_id: uuid.UUID | None
    ) -> dict[str, Any]:
        """Return per-camera health plus fleet counters.

        ``compound_id=None`` (global administrators) aggregates every compound.
        """
        stmt = select(Camera, Gate).join(Gate, Camera.gate_id == Gate.id)
        if compound_id is not None:
            stmt = stmt.where(Gate.compound_id == compound_id)
        stmt = stmt.order_by(Gate.code, Camera.name)
        rows = (await session.execute(stmt)).unique().all()
        workers = self._worker_state()
        now = datetime.now(UTC)
        cameras: list[dict[str, Any]] = []
        counts = {
            "total": 0,
            "online": 0,
            "offline": 0,
            "error": 0,
            "disabled": 0,
            "stale": 0,
            "demo": 0,
        }
        for camera, gate in rows:
            counts["total"] += 1
            status = str(camera.status)
            last_frame = camera.last_frame_at
            if last_frame is not None and last_frame.tzinfo is None:  # pragma: no cover
                last_frame = last_frame.replace(tzinfo=UTC)
            age = (now - last_frame).total_seconds() if last_frame else None
            stale = bool(
                camera.is_active
                and status == CameraStatus.ONLINE.value
                and (age is None or age > STALE_AFTER_SECONDS)
            )
            # ``disabled``/``online``/``error``/``offline`` stay mutually
            # exclusive so ``total == sum(statuses)``; ``stale`` and ``demo``
            # are flag counters layered on top.
            if not camera.is_active:
                counts["disabled"] += 1
            elif status == CameraStatus.ONLINE.value:
                counts["online"] += 1
            elif status == CameraStatus.ERROR.value:
                counts["error"] += 1
            else:
                counts["offline"] += 1
            if stale:
                counts["stale"] += 1
            if str(camera.source_type) == str(CameraSourceType.DEMO):
                counts["demo"] += 1
            worker = self._worker_for(workers, camera.id)
            cameras.append(
                {
                    "camera_id": str(camera.id),
                    "name": camera.name,
                    "gate_id": str(gate.id),
                    "gate_name": gate.name,
                    "gate_code": gate.code,
                    "source_type": str(camera.source_type),
                    "source": redact_source(camera.source_url),
                    "is_active": bool(camera.is_active),
                    "status": status,
                    "stale": stale,
                    "resolution": camera.resolution,
                    "fps_limit": camera.fps_limit,
                    "last_frame_at": last_frame.isoformat() if last_frame else None,
                    "frame_age_seconds": round(age, 1) if age is not None else None,
                    "last_error": camera.last_error,
                    "worker_alive": bool(worker.get("alive")) if worker else None,
                    "observed_fps": worker.get("fps") if worker else None,
                }
            )
        return {
            "compound_id": str(compound_id or uuid.UUID(int=0)),
            "generated_at": now.isoformat(),
            "stale_after_seconds": STALE_AFTER_SECONDS,
            "counts": counts,
            # Flat counters keep the original ``/cv/camera-health`` contract.
            **{key: value for key, value in counts.items()},
            "cameras": cameras,
        }

    async def snapshot(self, camera: Camera) -> bytes:
        """Grab a single live JPEG from a camera (Live Monitor thumbnails)."""
        import asyncio

        def _grab() -> bytes:
            from app.cv.pipeline import frame_to_jpeg

            source = OpenCVFrameSource(camera.source_url, name=camera.name)
            try:
                source.open()
                image = source.read()
            finally:
                source.close()
            if image is None:
                raise BadRequestError(
                    f"Camera '{camera.name}' did not return a frame. Check the stream URL."
                )
            return frame_to_jpeg(image, quality=settings.CV_SNAPSHOT_QUALITY)

        if (camera.source_type or "").lower() == str(CameraSourceType.DEMO):
            raise BadRequestError("Demo cameras have no live snapshot")
        return await asyncio.to_thread(_grab)

    # ----------------------------------------------------------------- bootstrap
    async def ensure_from_env(self, session: AsyncSession) -> list[str]:
        """Create/update cameras declared in ``CAMERAS_JSON``.

        Expected shape::

            [{"gate_code": "GATE-IN", "name": "Entry lane",
              "url": "rtsp://user:${CAM_IN_PASS}@10.0.0.11:554/Streaming/Channels/101",
              "source_type": "rtsp", "fps_limit": 5}]

        The function is idempotent: an existing camera with the same gate and
        name is updated in place, so restarting a container re-applies the
        compose file instead of duplicating rows.
        """
        raw = (settings.CAMERAS_JSON or "").strip()
        if not raw:
            return []
        try:
            entries = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("CAMERAS_JSON is not valid JSON: %s", exc)
            return []
        if not isinstance(entries, list):
            logger.error("CAMERAS_JSON must be a JSON list of camera objects")
            return []

        created: list[str] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            gate_code = str(entry.get("gate_code") or "").strip().upper()
            url = str(entry.get("url") or entry.get("source_url") or "").strip()
            if not gate_code or not url:
                logger.warning("CAMERAS_JSON entry skipped (needs gate_code and url): %s", entry)
                continue
            gate = await session.scalar(select(Gate).where(Gate.code == gate_code))
            if gate is None:
                logger.warning("CAMERAS_JSON: unknown gate code %s", gate_code)
                continue
            name = str(entry.get("name") or f"{gate_code} camera").strip()
            source_type = str(entry.get("source_type") or CameraSourceType.RTSP).lower()
            camera = await session.scalar(
                select(Camera).where(Camera.gate_id == gate.id, Camera.name == name)
            )
            if camera is None:
                camera = Camera(gate_id=gate.id, name=name, source_url=url)
                session.add(camera)
                created.append(f"{gate_code}/{name}")
            camera.source_type = CameraSourceType(source_type)
            camera.source_url = url
            camera.fps_limit = float(entry.get("fps_limit") or 5.0)
            camera.position = str(entry.get("position") or "front")
            camera.is_active = bool(entry.get("is_active", True))
            camera.status = CameraStatus.OFFLINE
            if camera.notes is None and entry.get("notes"):
                camera.notes = str(entry["notes"])
        if created or entries:
            await session.commit()
            logger.info("CAMERAS_JSON applied (%d new camera(s))", len(created))
        return created


camera_service = CameraService()


__all__ = ["CameraService", "ProbeResult", "STALE_AFTER_SECONDS", "camera_service"]
