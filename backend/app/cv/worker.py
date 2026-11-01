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


@dataclass(frozen=True, slots=True)
class ResultEnvelope:
    """A vision result tagged with the camera that produced it."""

    camera: CameraConfig
    result: VisionResult


def build_source(config: CameraConfig) -> FrameSource:
    """Instantiate the correct frame source for a camera record."""
    if config.source_type == CameraSourceType.DEMO:
        return DemoFrameSource(config.source_url, name=config.name)
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
        self.last_error: str | None = None

    def _emit_status(self, status: CameraStatus, error: str | None = None) -> None:
        self._last_status_at = time.monotonic()
        self.last_error = error
        try:
            self._on_status(
                StatusUpdate(
                    camera_id=self.config.camera_id,
                    status=status,
                    error=error,
                    at=datetime.now(UTC),
                    fps=self.observed_fps,
                )
            )
        except Exception:  # pragma: no cover - callback guard
            logger.exception("Status callback failed for camera %s", self.config.name)

    def run(self) -> None:  # noqa: C901 - explicit lifecycle is easier to follow
        interval = 1.0 / max(0.2, self.config.fps_limit)
        self._source = build_source(self.config)
        try:
            self._source.open()
        except VisionEngineError as exc:
            self._emit_status(CameraStatus.ERROR, str(exc))
            logger.error("Camera %s failed to open: %s", self.config.name, exc)
            return
        self._emit_status(CameraStatus.ONLINE)
        logger.info("Camera worker started: %s (%s)", self.config.name, self.config.source_type)

        previous = time.monotonic()
        while not self.stop_event.is_set():
            loop_started = time.monotonic()
            try:
                image = self._source.read()
            except Exception as exc:  # pragma: no cover - driver failure
                self._emit_status(CameraStatus.ERROR, f"Read failure: {exc}")
                time.sleep(2.0)
                continue
            if image is None:
                self._emit_status(CameraStatus.ERROR, "Camera stream unavailable")
                if self.stop_event.wait(2.0):
                    break
                continue

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

            elapsed = time.monotonic() - loop_started
            current = time.monotonic()
            frame_delta = current - previous
            previous = current
            if frame_delta > 0:
                smoothed = 1.0 / frame_delta
                self.observed_fps = (
                    smoothed if self.observed_fps is None else (0.9 * self.observed_fps + 0.1 * smoothed)
                )
            if time.monotonic() - self._last_status_at > 30:
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
