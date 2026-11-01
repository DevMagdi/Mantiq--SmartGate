"""Real-mode guarantees: camera transport, stream probing and no fake detections."""

from __future__ import annotations

import uuid
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.exceptions import VisionEngineError
from app.cv.sources import (
    DemoFrameSource,
    OpenCVFrameSource,
    expand_env_source,
    is_network_source,
    normalise_capture_target,
    redact_source,
)
from app.cv.utils import enhance_low_light, mean_brightness
from app.cv.worker import CameraConfig, build_source

API = "/api/v1"


# --------------------------------------------------------------------- helpers
def _camera_config(source_type: str, url: str) -> CameraConfig:
    return CameraConfig(
        camera_id=uuid.uuid4(),
        gate_id=uuid.uuid4(),
        compound_id=uuid.uuid4(),
        name="Test lane",
        gate_code="GATE-IN",
        source_type=source_type,
        source_url=url,
    )


class _FakeFrameSource:
    """Stand-in for ``OpenCVFrameSource`` so probes run without a real camera."""

    instances: list["_FakeFrameSource"] = []

    fail_next = False

    def __init__(self, url: str, name: str = "", **_: Any) -> None:
        self.url = url
        self.name = name
        self.frames_read = 0
        self.reconnects = 0
        self.closed = False
        self.fail = _FakeFrameSource.fail_next
        _FakeFrameSource.instances.append(self)

    def open(self) -> None:
        if self.fail:
            raise VisionEngineError("Unable to open camera stream: rtsp://camera/stream1")

    def read(self) -> np.ndarray | None:
        if self.fail:
            return None
        self.frames_read += 1
        return np.full((720, 1280, 3), 40, dtype=np.uint8)

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def fake_source(monkeypatch: pytest.MonkeyPatch) -> type[_FakeFrameSource]:
    from app.services import camera_service as module

    _FakeFrameSource.instances.clear()
    monkeypatch.setattr(module, "OpenCVFrameSource", _FakeFrameSource)
    monkeypatch.setattr(module, "SnapshotStore", lambda *a, **k: module.SnapshotStore())
    return _FakeFrameSource


# --------------------------------------------------------------- url handling
def test_env_placeholders_are_expanded_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAM_IN_PASS", "s3cret")
    url = "rtsp://admin:${CAM_IN_PASS}@10.0.0.11:554/Streaming/Channels/101"
    assert expand_env_source(url) == "rtsp://admin:s3cret@10.0.0.11:554/Streaming/Channels/101"
    # Unknown variables stay visible instead of silently emptying the URL.
    assert expand_env_source("rtsp://${NOPE}@host/1") == "rtsp://${NOPE}@host/1"


def test_credentials_are_masked_and_never_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    redacted = redact_source("rtsp://admin:Sup3rS3cret@10.0.0.11:554/live")
    assert "Sup3rS3cret" not in redacted
    assert redacted == "rtsp://admin:***@10.0.0.11:554/live"
    assert redact_source("0") == "0"


def test_capture_targets_cover_rtsp_usb_and_files() -> None:
    assert normalise_capture_target("rtsp://cam/1") == "rtsp://cam/1"
    assert normalise_capture_target("0") == 0
    assert normalise_capture_target("usb://1") == 1
    assert normalise_capture_target("file:///data/clip.mp4") == "/data/clip.mp4"
    assert is_network_source("http://cam/video.mjpg")
    assert not is_network_source("usb://0")
    with pytest.raises(VisionEngineError):
        normalise_capture_target("usb://front")


def test_source_reports_health_counters() -> None:
    source = OpenCVFrameSource("rtsp://camera/1", name="Entry")
    stats = source.stats()
    assert stats["kind"] == "opencv"
    assert stats["transport"] == "tcp"  # RTSP defaults to TCP for reliable plates
    assert stats["frames_read"] == 0
    assert "camera" in stats["source"]


# ------------------------------------------------------------- real-mode guard
def test_demo_cameras_are_refused_in_real_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CV_MODE", "real", raising=False)
    monkeypatch.setattr(settings, "CV_ALLOW_DEMO_SOURCES", False, raising=False)
    with pytest.raises(VisionEngineError):
        build_source(_camera_config("demo", "demo://entry-lane"))


def test_demo_cameras_are_allowed_in_mock_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CV_MODE", "mock", raising=False)
    source = build_source(_camera_config("demo", "demo://entry-lane"))
    assert isinstance(source, DemoFrameSource)


def test_rtsp_cameras_build_in_real_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CV_MODE", "real", raising=False)
    source = build_source(_camera_config("rtsp", "rtsp://10.0.0.11/Streaming/Channels/101"))
    assert isinstance(source, OpenCVFrameSource)


def test_real_mode_engine_has_no_mock_components() -> None:
    warnings = settings.cv_warnings()
    if settings.CV_MODE == "mock":  # the test profile deliberately runs mock
        assert any("simulated" in item for item in warnings)
    else:
        assert not any("simulated" in item for item in warnings)


# ---------------------------------------------------------------- night frames
def test_low_light_frames_are_brightened_for_ocr() -> None:
    # A uniform image has no local contrast for CLAHE to lift, so use a real
    # night-like gradient (IR foreground falling off towards the corners).
    dark = np.tile(np.linspace(4, 34, 320, dtype=np.uint8)[None, :, None], (240, 1, 3))
    brightened = enhance_low_light(dark)
    assert mean_brightness(brightened) > mean_brightness(dark) + 5
    assert brightened.shape == dark.shape


# -------------------------------------------------------------------- probing
def test_camera_probe_records_success(
    client: TestClient, admin_headers: dict[str, str], fake_source: type[_FakeFrameSource]
) -> None:
    cameras = client.get(f"{API}/cameras?page_size=50", headers=admin_headers).json()["items"]
    target = next(item for item in cameras if item["source_type"] == "rtsp")

    response = client.post(f"{API}/cv/cameras/{target['id']}/test", headers=admin_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["frames"] >= 1
    assert payload["width"] == 1280 and payload["height"] == 720
    assert payload["preview_url"], "a preview frame must be stored for the operator"
    assert payload["brightness"] is not None and payload["brightness"] < 60
    assert payload["hint"] is None
    # The camera row is updated so the dashboard reflects the probe.
    refreshed = client.get(f"{API}/cameras/{target['id']}", headers=admin_headers)
    assert refreshed.status_code == 200
    row = refreshed.json()
    assert row["status"] == "online"
    assert row["resolution"] == "1280x720"


def test_camera_probe_reports_actionable_failure(
    client: TestClient, admin_headers: dict[str, str], fake_source: type[_FakeFrameSource]
) -> None:
    cameras = client.get(f"{API}/cameras?page_size=50", headers=admin_headers).json()["items"]
    target = next(item for item in cameras if item["source_type"] == "rtsp")

    _FakeFrameSource.fail_next = True
    try:
        response = client.post(f"{API}/cv/cameras/{target['id']}/test", headers=admin_headers)
    finally:
        _FakeFrameSource.fail_next = False

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"]
    assert payload["hint"], "a failed probe must suggest what to check next"


def test_demo_camera_probe_is_rejected(
    client: TestClient, admin_headers: dict[str, str], fake_source: type[_FakeFrameSource]
) -> None:
    cameras = client.get(f"{API}/cameras?page_size=50", headers=admin_headers).json()["items"]
    demo_cameras = [item for item in cameras if item["source_type"] == "demo"]
    if not demo_cameras:  # real-mode deployments have no demo rows
        pytest.skip("no demo camera in this profile")
    response = client.post(f"{API}/cv/cameras/{demo_cameras[0]['id']}/test", headers=admin_headers)
    assert response.status_code == 400


def test_camera_health_lists_every_camera_and_masks_urls(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    response = client.get(f"{API}/cv/camera-health", headers=admin_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == payload["counts"]["total"] >= 1
    assert len(payload["cameras"]) == payload["total"]
    assert payload["stale_after_seconds"] > 0
    for camera in payload["cameras"]:
        assert camera["gate_code"]
        assert camera["source_type"] in {"rtsp", "demo", "usb", "file"}
        assert "stale" in camera
    # A resident must not be able to enumerate camera URLs.
    assert client.get(f"{API}/cv/camera-health").status_code in {401, 403}


def test_real_mode_status_is_explicit_about_simulation(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    response = client.get(f"{API}/cv/real-mode", headers=admin_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] in {"mock", "real"}
    assert isinstance(payload["real_detections_only"], bool)
    assert payload["barrier_driver"]
    assert "plate_detector" in payload["models"]
    if payload["mode"] == "mock":
        assert payload["real_detections_only"] is False
        assert any("simulated" in item.lower() for item in payload["warnings"])


def test_yolo_detector_keeps_only_plate_classes() -> None:
    """A multi-class model must not send "car" boxes to OCR."""
    from app.cv.detectors.yolo_plate import YOLOPlateDetector

    detector = YOLOPlateDetector("/tmp/does-not-exist.pt")
    detector._class_names = ["car", "plate", "person"]  # noqa: SLF001 - unit test
    assert detector._resolve_plate_classes() == {1}  # noqa: SLF001

    single = YOLOPlateDetector("/tmp/does-not-exist.pt")
    single._class_names = ["plate"]  # noqa: SLF001
    assert single._resolve_plate_classes() == {0}  # noqa: SLF001

    # Unknown naming -> no filtering, the model is already plate-only.
    generic = YOLOPlateDetector("/tmp/does-not-exist.pt")
    generic._class_names = ["obj", "license"]  # noqa: SLF001
    assert generic._resolve_plate_classes() is None  # noqa: SLF001


def test_real_mode_engine_never_invents_a_result_without_models() -> None:
    """No weights -> an explicit error, never a synthetic plate."""
    from app.cv.engine import VisionEngine

    class _RealConfig:
        CV_MODE = "real"
        CV_PLATE_MODEL_PATH = "/tmp/gatevision-missing-plate.pt"
        CV_PLATE_DETECTOR = "yolo"
        CV_OCR_ENGINE = "easyocr"
        CV_OCR_LANGUAGES = ["en"]
        CV_FACE_ENGINE = "insightface"
        CV_FACE_MODEL_NAME = "buffalo_l"
        CV_FACE_SIMILARITY_THRESHOLD = 0.45
        CV_PLATE_CONFIDENCE_THRESHOLD = 0.35
        CV_OCR_MIN_CONFIDENCE = 0.45
        CV_MAX_FPS = 5.0
        CV_FRAME_WIDTH = 1280
        CV_SNAPSHOT_QUALITY = 85
        CV_FACE_DET_SIZE = 640
        CV_YOLO_IMAGE_SIZE = 640
        CV_YOLO_IOU = 0.45
        CV_YOLO_DEVICE = ""
        CV_YOLO_HALF = False
        CV_PLATE_CLASS_NAMES = "plate"
        CV_MIN_PLATE_ASPECT = 1.6
        CV_MAX_PLATE_ASPECT = 7.0
        CV_OCR_ALLOWLIST = True
        CV_LOW_LIGHT_ENHANCE = False
        CV_LOW_LIGHT_THRESHOLD = 70.0
        CV_LOW_LIGHT_CLIP_LIMIT = 2.5
        CV_MOTION_MIN_AREA_RATIO = 0.0
        MEDIA_ROOT = "/tmp/gatevision-media"
        CV_DEMO_INTERVAL_SECONDS = 9.0

    engine = VisionEngine(_RealConfig())  # type: ignore[arg-type]
    image = np.zeros((240, 320, 3), dtype=np.uint8)
    with pytest.raises(VisionEngineError) as excinfo:
        engine.analyze_image(image)
    message = str(excinfo.value)
    assert "model" in message.lower() or "easyocr" in message.lower() or "insightface" in message.lower()
    assert engine.status()["engine_ready"] is False


@pytest.mark.asyncio
async def test_bootstrap_admin_is_available_without_demo_seeding(client: Any) -> None:
    """A production install (SEED_DEMO_DATA=false) must still be able to log in."""
    from sqlalchemy import func, select

    from app.db.session import session_scope
    from app.models.user import User
    from app.services.seed_service import seed_service

    async with session_scope() as session:
        admin = await seed_service.ensure_admin(session)
        assert admin is not None
        assert admin.role.value == "admin"
        email = admin.email

    # Idempotent: a second boot must not duplicate the account.
    async with session_scope() as session:
        again = await seed_service.ensure_admin(session)
        assert again is not None and again.email == email
        count = int(
            (await session.execute(select(func.count(User.id)).where(User.email == email))).scalar()
            or 0
        )
    assert count == 1


def test_camera_api_masks_stream_credentials(
    client: TestClient, admin_headers: dict[str, str], demo: dict[str, Any]
) -> None:
    """RTSP passwords must never leave the database through the API."""
    gate_id = demo["gate"]["id"]
    created = client.post(
        f"{API}/cameras",
        headers=admin_headers,
        json={
            "gate_id": gate_id,
            "name": "Masked lane",
            "source_type": "rtsp",
            "source_url": "rtsp://admin:S3cretPass@10.9.9.9:554/Streaming/Channels/101",
            "fps_limit": 5,
            "position": "front",
            "is_active": False,
        },
    )
    assert created.status_code in (200, 201), created.text
    body = created.json()
    assert "S3cretPass" not in body["source_url"]
    assert body["source_url"] == "rtsp://admin:***@10.9.9.9:554/Streaming/Channels/101"
    assert body["has_credentials"] is True

    # Sending the masked value back must not overwrite the stored URL.
    patched = client.patch(
        f"{API}/cameras/{body['id']}",
        headers=admin_headers,
        json={"source_url": body["source_url"], "fps_limit": 4},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["fps_limit"] == 4
    from app.db.session import session_scope
    from app.models.compound import Camera

    import asyncio
    import uuid as _uuid

    async def _stored() -> str:
        async with session_scope() as session:
            camera = await session.get(Camera, _uuid.UUID(body["id"]))
            assert camera is not None
            return camera.source_url

    assert asyncio.run(_stored()).endswith("S3cretPass@10.9.9.9:554/Streaming/Channels/101")
