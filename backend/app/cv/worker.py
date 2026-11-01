"""Per-camera capture worker running in its own thread."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Callable

from app.core.config import settings
from app.core.exceptions import VisionEngineError
from app.core.logging import get_logger
from app.cv.engine import VisionEngine
from app.cv.gallery import FaceGallery
from app.cv.pipeline import Deduplicator
from app.cv.sources import DemoFrameSource, FrameSource, OpenCVFrameSource
from app.cv.types import RawFrame, VisionOptions, VisionResult
from app.models.enums import CameraSourceType, CameraStatus

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CameraConfig:
    """Static configuration handed to a camera worker."""

    camera_id: uuid.UUID
    gate_id: uuid.UUID
    compound_id: uuid.UUID
    name: str
    gate_code: str
    source_type: str
    source_url: str
    fps_limit: float = 5.0
    position: str = "front"
    vision: VisionOptions = field(default_factory=VisionOptions)


@dataclass(frozen=True, slots=True)
class StatusUpdate:
    """Runtime status emitted by a worker."""

    camera_id: uuid.UUID
    status: CameraStatus
    error: str | None = None
    at: datetime = field(default_factory=lambda: datetime.now(UTC))
    fps: float | None = None
    frames_read: int = 0
    reconnects: int = 0
    resolution: str | None = None


@dataclass(frozen=True, slots=True)
class ResultEnvelope:
    """A vision result tagged with the camera that produced it."""

    camera: CameraConfig
    result: VisionResult


def demo_source_allowed(mode: str | None = None) -> bool:
    """Return ``True`` when a synthetic demo feed may be served.

    Real deployments must never show invented detections, so demo sources are
    rejected unless the operator explicitly asked for ``CV_MODE=mock`` (or set
    ``CV_ALLOW_DEMO_SOURCES=true`` for a staged demonstration).
    """
    active_mode = (mode or settings.CV_MODE or "real").lower()
    return active_mode == "mock" or settings.CV_ALLOW_DEMO_SOURCES


def build_source(config: CameraConfig) -> FrameSource:
    """Instantiate the correct frame source for a camera record."""
    if config.source_type == CameraSourceType.DEMO:
        if not demo_source_allowed():
            raise VisionEngineError(
                f"Camera '{config.name}' is configured as a demo feed, but the vision engine "
                "runs in real mode. Set a real RTSP/USB source URL for this camera "
                "(Settings → Cameras) or start with CV_MODE=mock."
            )
        return DemoFrameSource(config.source_url, name=config.name)
    source_type = (config.source_type or "").lower()
    if source_type == str(CameraSourceType.USB) and not config.source_url.strip().isdigit():
        # Accept "usb://1" and bare indexes; anything else is treated as a path.
        pass
    return OpenCVFrameSource(
        config.source_url, name=config.name, width=settings.CV_FRAME_WIDTH
    )


class CameraWorker(threading.Thread):
    """Reads frames, runs inference, and pushes results to the manager.

    The worker never touches the database or the event loop directly: it emits
    :class:`ResultEnvelope` / :class:`StatusUpdate` objects through callbacks that
    the async manager consumes.
    """

    def __init__(
        self,
        config: CameraConfig,
        engine: VisionEngine,
        gallery_provider: Callable[[], FaceGallery],
        on_result: Callable[[ResultEnvelope], None],
        on_status: Callable[[StatusUpdate], None],
        stop_event: threading.Event | None = None,
    ) -> None:
        super().__init__(name=f"camera-{config.name}", daemon=True)
        self.config = config
        self.engine = engine
        self._gallery_provider = gallery_provider
        self._on_result = on_result
        self._on_status = on_status
        self.stop_event = stop_event or threading.Event()
        self.deduplicator = Deduplicator()
        self._source: FrameSource | None = None
        self._sequence = 0
        self._last_status_at = 0.0
        self.observed_fps: float | None = None
        self.last_resolution: str | None = None
        self._first_frame_seen = False
        self.last_error: str | None = None
        self._status_key: tuple[str, str | None] | None = None

    def _open_with_retry(self, attempts: int = 0) -> None:
        """Open the stream, retrying with backoff until it works or we stop.

        ``attempts=0`` means "keep trying forever": camera workers must survive a
        camera that boots later than the container (very common with NVRs).
        """
        if self._source is None:
            return
        delay = max(0.2, settings.CV_RECONNECT_DELAY_SECONDS)
        max_delay = max(delay, settings.CV_RECONNECT_MAX_DELAY_SECONDS)
        attempt = 0
        while not self.stop_event.is_set():
            if attempts and attempt >= attempts:
                return
            try:
                self._source.open()
            except VisionEngineError as exc:
                attempt += 1
                self._emit_status(CameraStatus.ERROR, str(exc))
                logger.warning(
                    "Camera %s open failed (attempt %s): %s", self.config.name, attempt, exc
                )
                if self.stop_event.wait(delay):
                    return
                delay = min(delay * 2, max_delay)
                continue
            self._first_frame_seen = False
            self._emit_status(CameraStatus.ONLINE)
            return

    # Repeated identical failures are throttled: a camera that is off for an
    # hour must not write a database row every second.
    STATUS_REPEAT_SECONDS = 15.0

    def _emit_status(
        self, status: CameraStatus, error: str | None = None, *, force: bool = False
    ) -> None:
        now_monotonic = time.monotonic()
        key = (status.value, error)
        if (
            not force
            and key == self._status_key
            and now_monotonic - self._last_status_at < self.STATUS_REPEAT_SECONDS
        ):
            return
        self._status_key = key
        self._last_status_at = now_monotonic
        self.last_error = error
        try:
            self._on_status(
                StatusUpdate(
                    camera_id=self.config.camera_id,
                    status=status,
                    error=error,
                    at=datetime.now(UTC),
                    fps=self.observed_fps,
                    frames_read=self._source.frames_read if self._source else 0,
                    reconnects=self._source.reconnects if self._source else 0,
                    resolution=self.last_resolution,
                )
            )
        except Exception:  # pragma: no cover - callback guard
            logger.exception("Status callback failed for camera %s", self.config.name)

    def run(self) -> None:  # noqa: C901 - explicit lifecycle is easier to follow
        interval = 1.0 / max(0.2, self.config.fps_limit)
        try:
            self._source = build_source(self.config)
        except VisionEngineError as exc:
            # Misconfiguration (demo feed in real mode, bad model path, …):
            # report it once and stop instead of retrying an impossible stream.
            self._emit_status(CameraStatus.ERROR, str(exc))
            logger.error("Camera %s cannot start: %s", self.config.name, exc)
            return
        self._open_with_retry()
        if self._source is None:
            return
        logger.info("Camera worker started: %s (%s)", self.config.name, self.config.source_type)

        previous = time.monotonic()
        last_frame_monotonic = time.monotonic()
        while not self.stop_event.is_set():
            loop_started = time.monotonic()
            try:
                image = self._source.read()
            except Exception as exc:  # pragma: no cover - driver failure
                self._emit_status(CameraStatus.ERROR, f"Read failure: {exc}")
                if self.stop_event.wait(2.0):
                    break
                continue
            if image is None:
                # The source already backed off; keep reporting so the dashboard
                # shows the camera as offline with the transport error.
                self._emit_status(
                    CameraStatus.ERROR,
                    getattr(self._source, "last_error", None) or "Camera stream unavailable",
                )
                if self.stop_event.wait(0.5):
                    break
                continue
            last_frame_monotonic = time.monotonic()
            height, width = image.shape[:2]
            self.last_resolution = f"{int(width)}x{int(height)}"
            if not self._first_frame_seen:
                # Publish the resolution (and a fresh ``last_frame_at``) as soon
                # as real pixels arrive instead of waiting for the heartbeat.
                self._first_frame_seen = True
                # ``force`` so the resolution/first-frame timestamp reaches the
                # dashboard immediately instead of after the heartbeat window.
                self._emit_status(CameraStatus.ONLINE, force=True)

            self._sequence += 1
            now = datetime.now(UTC)
            raw_frame = RawFrame(
                image=image,
                camera_id=self.config.camera_id,
                gate_id=self.config.gate_id,
                source_id=self.config.source_url,
                captured_at=now,
                sequence=self._sequence,
                meta=dict(self._source.meta()),
            )
            try:
                result = self.engine.process(
                    raw_frame,
                    gallery=self._gallery_provider(),
                    annotate=True,
                    options=self.config.vision,
                )
            except VisionEngineError as exc:
                self._emit_status(CameraStatus.ERROR, str(exc))
                logger.error("Inference failed for camera %s: %s", self.config.name, exc)
                if self.stop_event.wait(5.0):
                    break
                continue
            except Exception as exc:  # pragma: no cover - unexpected inference error
                logger.exception("Unexpected pipeline error on camera %s", self.config.name)
                self._emit_status(CameraStatus.ERROR, f"Pipeline error: {exc}")
                if self.stop_event.wait(3.0):
                    break
                continue

            if (result.plate is not None or result.face is not None) and self.deduplicator.should_emit(result):
                try:
                    self._on_result(ResultEnvelope(camera=self.config, result=result))
                except Exception:  # pragma: no cover - callback guard
                    logger.exception("Result callback failed for camera %s", self.config.name)

            # Stall guard: a TCP socket that stays open while frames stop
            # arriving (camera reboot, PoE hiccup) must be reopened.
            if (
                settings.CV_STALL_TIMEOUT_SECONDS > 0
                and time.monotonic() - last_frame_monotonic > settings.CV_STALL_TIMEOUT_SECONDS
            ):
                logger.warning(
                    "Camera %s stalled for %.0fs; reopening the stream",
                    self.config.name,
                    time.monotonic() - last_frame_monotonic,
                )
                self._emit_status(CameraStatus.ERROR, "Stream stalled (no frames); reconnecting")
                self._source.close()
                self._open_with_retry()
                if self._source is None:
                    break
                last_frame_monotonic = time.monotonic()
                continue

            elapsed = time.monotonic() - loop_started
            current = time.monotonic()
            frame_delta = current - previous
            previous = current
            if frame_delta > 0:
                smoothed = 1.0 / frame_delta
                self.observed_fps = (
                    smoothed if self.observed_fps is None else (0.9 * self.observed_fps + 0.1 * smoothed)
                )
            if time.monotonic() - self._last_status_at >= self.STATUS_REPEAT_SECONDS:
                self._emit_status(CameraStatus.ONLINE)
            remaining = interval - elapsed
            if remaining > 0 and self.stop_event.wait(remaining):
                break

        if self._source is not None:
            self._source.close()
        self._emit_status(CameraStatus.OFFLINE)
        logger.info("Camera worker stopped: %s", self.config.name)

    def stop(self) -> None:
        """Signal the worker to stop and wake it from any sleep."""
        self.stop_event.set()


__all__ = [
    "CameraConfig",
    "CameraWorker",
    "ResultEnvelope",
    "StatusUpdate",
    "build_source",
]
