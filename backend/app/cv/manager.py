"""Async camera manager: lifecycle, galleries, persistence hand-off and events."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import settings
from app.core.events import publish_event
from app.core.logging import get_logger
from app.cv.engine import VisionEngine, get_vision_engine
from app.cv.gallery import FaceGallery, GalleryEntry, MutableGallery
from app.cv.worker import CameraConfig, CameraWorker, ResultEnvelope, StatusUpdate
from app.db.session import session_scope
from app.models.compound import Camera, Gate
from app.models.enums import CameraStatus, ResidentStatus
from app.models.people import Resident
from app.models.security import FaceEmbedding

logger = get_logger(__name__)

ResultHandler = Callable[[ResultEnvelope], Awaitable[None]]


async def load_face_gallery(compound_id: uuid.UUID) -> FaceGallery:
    """Load active resident face embeddings for one compound."""
    async with session_scope() as session:
        stmt = (
            select(FaceEmbedding)
            .join(Resident, FaceEmbedding.resident_id == Resident.id)
            .where(
                FaceEmbedding.compound_id == compound_id,
                FaceEmbedding.is_active.is_(True),
                Resident.status == ResidentStatus.ACTIVE,
            )
        )
        embeddings = list((await session.execute(stmt)).scalars().unique().all())
    entries = [
        GalleryEntry(
            resident_id=embedding.resident.id,  # type: ignore[union-attr]
            embedding=tuple(embedding.embedding),
            embedding_id=embedding.id,
            model_name=embedding.model_name,
            label=embedding.resident.full_name if embedding.resident else None,
        )
        for embedding in embeddings
        if embedding.resident is not None
    ]
    return FaceGallery(entries)


class CameraManager:
    """Supervises camera workers and bridges them to async services."""

    def __init__(
        self,
        engine: VisionEngine | None = None,
        on_result: ResultHandler | None = None,
        result_queue_size: int = 2000,
    ) -> None:
        self.engine = engine or get_vision_engine()
        self.on_result = on_result
        self._loop: asyncio.AbstractEventLoop | None = None
        self._workers: dict[uuid.UUID, CameraWorker] = {}
        self._configs: dict[uuid.UUID, CameraConfig] = {}
        self._galleries: dict[uuid.UUID, MutableGallery] = {}
        self._result_queue: asyncio.Queue[ResultEnvelope] = asyncio.Queue(maxsize=result_queue_size)
        self._status_queue: asyncio.Queue[StatusUpdate] = asyncio.Queue(maxsize=500)
        self._tasks: list[asyncio.Task[None]] = []
        self._running = False

    # --------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        """Load cameras, refresh galleries and start all supervision tasks."""
        if self._running:
            return
        self._loop = asyncio.get_running_loop()
        ready = await self.engine.warmup_async()
        if not ready:
            logger.error("Vision engine is not ready; cameras will still be monitored")
        await self._load_galleries()
        await self._sync_cameras()
        self._running = True
        self._tasks = [
            asyncio.create_task(self._consume_results(), name="cv-result-consumer"),
            asyncio.create_task(self._consume_status(), name="cv-status-consumer"),
            asyncio.create_task(self._supervise(), name="cv-supervisor"),
        ]
        logger.info("Camera manager started with %d worker(s)", len(self._workers))

    async def stop(self) -> None:
        """Stop every worker and cancel supervision tasks."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()
        for worker in list(self._workers.values()):
            worker.stop()
        for worker in list(self._workers.values()):
            await asyncio.to_thread(worker.join, 3.0)
        self._workers.clear()
        logger.info("Camera manager stopped")

    # ------------------------------------------------------------------ cameras
    async def _sync_cameras(self) -> None:
        async with session_scope() as session:
            stmt = (
                select(Camera, Gate)
                .join(Gate, Camera.gate_id == Gate.id)
                .where(Camera.is_active.is_(True), Gate.is_active.is_(True))
            )
            rows = (await session.execute(stmt)).unique().all()
            configs = [
                CameraConfig(
                    camera_id=camera.id,
                    gate_id=gate.id,
                    compound_id=gate.compound_id,
                    name=camera.name,
                    gate_code=gate.code,
                    source_type=str(camera.source_type),
                    source_url=camera.source_url,
                    fps_limit=min(camera.fps_limit or 5.0, settings.CV_MAX_FPS),
                    position=camera.position,
                )
                for camera, gate in rows
            ]

        active_ids = {config.camera_id for config in configs}
        for camera_id in list(self._workers):
            if camera_id not in active_ids:
                worker = self._workers.pop(camera_id)
                worker.stop()
                self._configs.pop(camera_id, None)
                logger.info("Camera removed from supervisor: %s", worker.config.name)
        for config in configs:
            if config.camera_id in self._workers:
                continue
            if config.compound_id not in self._galleries:
                self._galleries[config.compound_id] = MutableGallery(await self._build_gallery(config.compound_id))
            self._start_worker(config)
        if not configs:
            logger.warning("No active cameras configured; add a camera from the dashboard")

    def _start_worker(self, config: CameraConfig) -> None:
        gallery = self._galleries.setdefault(config.compound_id, MutableGallery())
        worker = CameraWorker(
            config=config,
            engine=self.engine,
            gallery_provider=lambda g=gallery: g.snapshot(),
            on_result=self._enqueue_result,
            on_status=self._enqueue_status,
        )
        self._workers[config.camera_id] = worker
        self._configs[config.camera_id] = config
        worker.start()
        logger.info("Camera worker launched: %s", config.name)

    # ----------------------------------------------------------------- galleries
    async def _build_gallery(self, compound_id: uuid.UUID) -> FaceGallery:
        try:
            gallery = await load_face_gallery(compound_id)
            logger.info("Face gallery loaded for compound %s (%d entries)", compound_id, len(gallery))
            return gallery
        except Exception as exc:  # pragma: no cover - database hiccup
            logger.error("Failed to load face gallery for %s: %s", compound_id, exc)
            return FaceGallery()

    async def _load_galleries(self) -> None:
        async with session_scope() as session:
            stmt = select(Gate.compound_id).distinct()
            compound_ids = [row[0] for row in (await session.execute(stmt)).all()]
        for compound_id in compound_ids:
            gallery = await self._build_gallery(compound_id)
            if compound_id in self._galleries:
                self._galleries[compound_id].replace(gallery)
            else:
                self._galleries[compound_id] = MutableGallery(gallery)

    async def refresh_galleries(self) -> None:
        """Reload every gallery (call after enrollment changes)."""
        await self._load_galleries()

    # ------------------------------------------------------------------ queues
    def _enqueue_result(self, envelope: ResultEnvelope) -> None:
        if self._loop is None:
            return

        def _put() -> None:
            if self._result_queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    self._result_queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                self._result_queue.put_nowait(envelope)

        self._loop.call_soon_threadsafe(_put)

    def _enqueue_status(self, update: StatusUpdate) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(
            lambda: self._status_queue.put_nowait(update)
            if not self._status_queue.full()
            else None
        )

    async def _consume_results(self) -> None:
        while True:
            envelope = await self._result_queue.get()
            if self.on_result is None:
                continue
            try:
                await self.on_result(envelope)
            except Exception:  # pragma: no cover - keep the consumer alive
                logger.exception("Failed to process detection for camera %s", envelope.camera.name)

    async def _consume_status(self) -> None:
        while True:
            update = await self._status_queue.get()
            try:
                await self._apply_status(update)
            except Exception:  # pragma: no cover
                logger.exception("Failed to persist camera status")

    async def _apply_status(self, update: StatusUpdate) -> None:
        compound_id: uuid.UUID | None = None
        gate_id: uuid.UUID | None = None
        async with session_scope() as session:
            camera = await session.get(Camera, update.camera_id)
            if camera is None:
                return
            gate = await session.get(Gate, camera.gate_id)
            compound_id = gate.compound_id if gate else None
            gate_id = gate.id if gate else None
            previous = camera.status
            camera.status = update.status
            if update.status == CameraStatus.ONLINE:
                camera.last_frame_at = update.at
                camera.last_error = None
            elif update.error:
                camera.last_error = update.error[:2000]
        if previous != update.status or update.status == CameraStatus.ERROR:
            await publish_event(
                "camera.status",
                {
                    "camera_id": str(update.camera_id),
                    "compound_id": str(compound_id) if compound_id else None,
                    "gate_id": str(gate_id) if gate_id else None,
                    "status": update.status.value,
                    "error": update.error,
                    "at": update.at.isoformat(),
                    "fps": round(update.fps, 2) if update.fps else None,
                },
            )
        if update.status == CameraStatus.ERROR:
            logger.warning("Camera error: %s", update.error)

    # --------------------------------------------------------------- supervisor
    async def _supervise(self) -> None:
        while True:
            try:
                await asyncio.sleep(45)
                await self._sync_cameras()
                await self._load_galleries()
                for camera_id, worker in list(self._workers.items()):
                    if not worker.is_alive() and not worker.stop_event.is_set():
                        logger.warning("Restarting dead camera worker: %s", worker.config.name)
                        config = self._configs.get(camera_id)
                        if config is None:
                            continue
                        self._workers.pop(camera_id, None)
                        self._start_worker(config)
            except asyncio.CancelledError:  # pragma: no cover
                raise
            except Exception:  # pragma: no cover
                logger.exception("Camera supervisor iteration failed")
                await asyncio.sleep(10)

    # ------------------------------------------------------------------- status
    def status(self) -> dict[str, object]:
        """Return in-process worker status (used by the API in single-process mode)."""
        return {
            "running": self._running,
            "workers": [
                {
                    "camera_id": str(camera_id),
                    "name": worker.config.name,
                    "gate_id": str(worker.config.gate_id),
                    "alive": worker.is_alive(),
                    "fps": round(worker.observed_fps, 2) if worker.observed_fps else None,
                    "last_error": worker.last_error,
                }
                for camera_id, worker in self._workers.items()
            ],
            "galleries": {
                str(compound_id): {
                    "entries": len(gallery),
                    "loaded_at": datetime.now(UTC).isoformat(),
                }
                for compound_id, gallery in self._galleries.items()
            },
        }


_manager: CameraManager | None = None


def get_camera_manager() -> CameraManager | None:
    """Return the running camera manager (``None`` in the API process by default)."""
    return _manager


def set_camera_manager(manager: CameraManager | None) -> None:
    """Register the process-wide manager."""
    global _manager
    _manager = manager
