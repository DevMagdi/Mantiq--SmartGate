"""Worker → manager status plumbing: nothing may be dropped on the floor.

A regression test for the silent ``AttributeError`` that used to leave every
camera stuck on ``offline`` in the dashboard even though frames were flowing.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.session import session_scope
from app.cv.manager import CameraManager
from app.cv.worker import StatusUpdate
from app.models.compound import Camera
from app.models.enums import CameraStatus
from fastapi.testclient import TestClient


@pytest.mark.asyncio
async def test_status_update_carries_resolution() -> None:
    update = StatusUpdate(camera_id=uuid.uuid4(), status=CameraStatus.ONLINE, resolution="1280x720")
    assert update.resolution == "1280x720"
    assert StatusUpdate(camera_id=uuid.uuid4(), status=CameraStatus.OFFLINE).resolution is None


@pytest.mark.asyncio
async def test_manager_persists_worker_status_and_resolution(client: TestClient) -> None:
    async with session_scope() as session:
        cam = (await session.execute(select(Camera).order_by(Camera.created_at).limit(1))).scalar_one()
        camera_id = cam.id

    manager = CameraManager()
    await manager._apply_status(  # noqa: SLF001 - the plumbing under test
        StatusUpdate(
            camera_id=camera_id,
            status=CameraStatus.ONLINE,
            fps=4.5,
            frames_read=120,
            reconnects=1,
            resolution="1920x1080",
        )
    )

    async with session_scope() as session:
        refreshed = await session.get(Camera, camera_id)
        assert refreshed is not None
        assert refreshed.status == CameraStatus.ONLINE
        assert refreshed.resolution == "1920x1080"
        assert refreshed.last_frame_at is not None
        assert refreshed.last_error is None


@pytest.mark.asyncio
async def test_manager_records_error_message_for_offline_stream(client: TestClient) -> None:
    async with session_scope() as session:
        cam = (await session.execute(select(Camera).order_by(Camera.created_at).limit(1))).scalar_one()
        camera_id = cam.id

    manager = CameraManager()
    await manager._apply_status(  # noqa: SLF001
        StatusUpdate(
            camera_id=camera_id,
            status=CameraStatus.ERROR,
            error="Connection refused",  # pragma: allowlist secret - not a secret
        )
    )

    async with session_scope() as session:
        refreshed = await session.get(Camera, camera_id)
        assert refreshed is not None
        assert refreshed.status == CameraStatus.ERROR
        assert refreshed.last_error == "Connection refused"


def test_first_frame_publishes_resolution_immediately() -> None:
    """The dashboard must show 1280x720 within a second, not after 15 s."""
    import time
    import uuid as _uuid

    from app.cv.engine import get_vision_engine
    from app.cv.gallery import FaceGallery
    from app.cv.worker import CameraConfig, CameraWorker

    events: list[tuple[str, str | None]] = []
    config = CameraConfig(
        camera_id=_uuid.uuid4(),
        gate_id=_uuid.uuid4(),
        compound_id=_uuid.uuid4(),
        name="status-probe",
        gate_code="GATE-IN",
        source_type="demo",
        source_url="demo://entry-lane",
        fps_limit=2.0,
    )
    worker = CameraWorker(
        config,
        get_vision_engine(),
        lambda: FaceGallery(entries=()),
        lambda envelope: None,
        lambda status: events.append((status.status.value, status.resolution)),
    )
    worker.start()
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not any(r for _, r in events):
            time.sleep(0.1)
    finally:
        worker.stop_event.set()
        worker.join(timeout=5)

    assert any(resolution == "1280x720" for _, resolution in events), events
    first_with_resolution = next(item for item in events if item[1])
    assert first_with_resolution[0] == "online"
