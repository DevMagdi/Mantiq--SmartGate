"""Standalone computer-vision runner process.

Run with ``python -m app.cv.runner``. It connects to the same database and Redis
event bus as the API, so detections appear in the dashboard in real time.
"""

from __future__ import annotations

import asyncio
import signal
from typing import Any

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.cv.engine import get_vision_engine
from app.cv.manager import CameraManager
from app.cv.worker import ResultEnvelope

logger = get_logger(__name__)


async def handle_result(envelope: ResultEnvelope) -> None:
    """Persist a detection, evaluate access and publish events."""
    from app.services.detection_service import DetectionService

    service = DetectionService()
    await service.handle_envelope(envelope)


async def run() -> None:
    """Start the camera manager and block until SIGTERM/SIGINT."""
    if not settings.CV_ENABLED:
        logger.warning("CV_ENABLED=false — camera runner will idle without workers")
    engine = get_vision_engine()
    logger.info(
        "Starting GateVision CV runner (mode=%s, plate=%s, ocr=%s, face=%s)",
        settings.CV_MODE,
        settings.CV_PLATE_DETECTOR,
        settings.CV_OCR_ENGINE,
        settings.CV_FACE_ENGINE,
    )
    manager = CameraManager(engine=engine, on_result=handle_result)
    await manager.start()

    stop_event = asyncio.Event()

    def _request_stop(*_: Any) -> None:
        logger.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:  # pragma: no cover - Windows
            signal.signal(sig, _request_stop)

    try:
        await stop_event.wait()
    finally:
        await manager.stop()
        logger.info("GateVision CV runner stopped")


def main() -> None:
    """Entry point for ``python -m app.cv.runner``."""
    configure_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)
    settings.ensure_directories()
    asyncio.run(run())


if __name__ == "__main__":
    main()
